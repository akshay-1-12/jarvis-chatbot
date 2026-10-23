import base64
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app as chatbot
from google.genai import errors
from werkzeug.datastructures import FileStorage


class FakeModels:
    def __init__(self, reply="You can do this!", error=None):
        self.reply = reply
        self.error = error
        self.contents = None
        self.model = None
        self.config = None

    def generate_content_stream(self, *, model, contents, config):
        self.model = model
        self.contents = contents
        self.config = config
        if self.error:
            raise self.error
        yield SimpleNamespace(text=self.reply)


class FakeHttpResponse:
    def __init__(self, status_code=200, lines=None):
        self.status_code = status_code
        self.lines = lines or []

    def iter_lines(self):
        yield from self.lines


class FakeHttpStream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self.response

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class ChatbotRouteTests(unittest.TestCase):
    def setUp(self):
        chatbot.app.config.update(TESTING=True)
        self.client = chatbot.app.test_client()

    def test_home_renders_chat_interface(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'class="side-brand">JARVIS AI<', response.data)
        self.assertIn(b'class="robot-face"', response.data)
        self.assertIn(b'class="robot-eye"', response.data)
        self.assertNotIn(b'class="core-letter">J</div>', response.data)
        self.assertNotIn(b'class="core-center">J</div>', response.data)
        self.assertNotIn(b"jarvis-logo.png", response.data)
        self.assertIn(b"Hello, I'm ", response.data)
        self.assertIn(b"Jarvis.", response.data)
        self.assertIn(b'id="sideExplainLanguage"', response.data)
        self.assertIn(b'id="mobileExplainLanguage"', response.data)
        self.assertIn(b'class="settings-ok"', response.data)
        self.assertIn(b'value="apply">OK</button>', response.data)
        self.assertEqual(response.data.count(b'value="hi"'), 2)
        self.assertIn(b'Explain latest answer or file', response.data)
        self.assertNotIn(b'id="autoSpeak"', response.data)
        self.assertNotIn(b'data-reading-toggle', response.data)
        self.assertNotIn(b'data-reading-stop', response.data)
        self.assertIn(b'class="explain-button"', response.data)

    def test_uploaded_logo_is_not_used(self):
        response = self.client.get("/static/jarvis-logo.png")

        self.assertEqual(response.status_code, 404)

    def test_chat_returns_gemini_reply(self):
        fake_models = FakeModels()
        fake_client = SimpleNamespace(models=fake_models)
        conversation = [
            {"role": "user", "text": "I need a study plan."},
            {"role": "model", "text": "What subject are you studying?"},
            {"role": "user", "text": "Biology."},
        ]

        with patch.object(chatbot, "client", fake_client):
            response = self.client.post(
                "/api/chat",
                json={"messages": conversation},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.content_type)
        self.assertIn('data: "You can do this!"', response.get_data(as_text=True))
        self.assertIn("Akshay Subhash Dodke", fake_models.config.system_instruction)
        self.assertIn("Software Development and Android", fake_models.config.system_instruction)
        self.assertIn("natural phrasing", fake_models.config.system_instruction)
        self.assertIn("never claim to be human", fake_models.config.system_instruction)
        self.assertIn("support Marathi and Hindi", fake_models.config.system_instruction)
        self.assertEqual(fake_models.contents[-1].parts[0].text, "Biology.")
        self.assertEqual(
            [
                (item.role, item.parts[0].text)
                for item in fake_models.contents[:-1]
            ],
            [
                ("user", "I need a study plan."),
                ("model", "What subject are you studying?"),
            ],
        )

    def test_speech_returns_gemini_generated_audio(self):
        audio = b"streamed-pcm"
        fake_response = FakeHttpResponse(lines=[
            "data: " + json.dumps({
                "event_type": "step.delta",
                "delta": {
                    "type": "audio",
                    "data": base64.b64encode(audio[:6]).decode("ascii"),
                },
            }),
            "",
            "data: " + json.dumps({
                "event_type": "step.delta",
                "delta": {
                    "type": "audio",
                    "data": base64.b64encode(audio[6:]).decode("ascii"),
                },
            }),
            "",
            "data: [DONE]",
            "",
        ])

        with patch.object(chatbot, "API_KEY", "test-key"), patch.object(
            chatbot.httpx, "stream", return_value=FakeHttpStream(fake_response)
        ) as post:
            response = self.client.post(
                "/api/speech",
                json={
                    "text": "नमस्कार, अक्षय.",
                    "gender": "female",
                    "language": "mr",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "audio/l16")
        self.assertEqual(response.data, audio)
        self.assertEqual(
            post.call_args.args[1],
            "https://generativelanguage.googleapis.com/v1beta/interactions",
        )
        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], "test-key")
        request_payload = post.call_args.kwargs["json"]
        self.assertEqual(request_payload["model"], chatbot.TTS_MODEL)
        self.assertEqual(chatbot.TTS_MODEL, "gemini-3.8-flash-tts")
        self.assertEqual(
            request_payload["generation_config"]["speech_config"],
            [{"voice": "Kore"}],
        )
        self.assertIn(
            "Speak only in Marathi. Use fluent Marathi as spoken in Maharashtra",
            request_payload["input"][0]["content"][0]["annotations"][0]["style"],
        )
        self.assertTrue(request_payload["stream"])
        self.assertEqual(
            request_payload["response_format"]["mime_type"],
            "audio/l16",
        )

    def test_speech_stream_flushes_final_event_without_blank_line(self):
        audio = b"final-pcm"
        fake_response = FakeHttpResponse(lines=[
            "data: " + json.dumps({
                "event_type": "step.delta",
                "delta": {
                    "type": "audio",
                    "data": base64.b64encode(audio).decode("ascii"),
                },
            }),
        ])

        with patch.object(chatbot, "API_KEY", "test-key"), patch.object(
            chatbot.httpx, "stream", return_value=FakeHttpStream(fake_response)
        ):
            response = self.client.post(
                "/api/speech",
                json={"text": "मराठी चाचणी.", "language": "mr"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, audio)

    def test_speech_reports_provider_rate_limit(self):
        fake_response = FakeHttpResponse(status_code=429)
        with patch.object(chatbot, "API_KEY", "test-key"), patch.object(
            chatbot.httpx, "stream", return_value=FakeHttpStream(fake_response)
        ):
            response = self.client.post(
                "/api/speech",
                json={"text": "मराठी चाचणी.", "language": "mr"},
            )

        self.assertEqual(response.status_code, 502)
        self.assertIn("usage limit", response.get_json()["error"])

    def test_speech_reports_provider_auth_and_model_errors(self):
        for status_code, expected in (
            (401, "did not allow speech"),
            (403, "did not allow speech"),
            (404, "cannot access the speech model"),
        ):
            with self.subTest(status_code=status_code):
                fake_response = FakeHttpResponse(status_code=status_code)
                with patch.object(chatbot, "API_KEY", "test-key"), patch.object(
                    chatbot.httpx,
                    "stream",
                    return_value=FakeHttpStream(fake_response),
                ):
                    response = self.client.post(
                        "/api/speech",
                        json={"text": "मराठी चाचणी.", "language": "mr"},
                    )

                self.assertEqual(response.status_code, 502)
                self.assertIn(expected, response.get_json()["error"])

    def test_speech_reports_connection_error(self):
        with patch.object(chatbot, "API_KEY", "test-key"), patch.object(
            chatbot.httpx,
            "stream",
            side_effect=chatbot.httpx.ConnectError("offline"),
        ):
            response = self.client.post(
                "/api/speech",
                json={"text": "मराठी चाचणी.", "language": "mr"},
            )

        self.assertEqual(response.status_code, 502)
        self.assertIn("Could not reach Gemini", response.get_json()["error"])

    def test_speech_without_audio_returns_empty_stream_for_client_fallback(self):
        fake_response = FakeHttpResponse(lines=["data: [DONE]", ""])
        with patch.object(chatbot, "API_KEY", "test-key"), patch.object(
            chatbot.httpx, "stream", return_value=FakeHttpStream(fake_response)
        ):
            response = self.client.post(
                "/api/speech",
                json={"text": "नमस्कार.", "language": "mr"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"")

    def test_speech_invalid_audio_chunk_is_not_forwarded(self):
        fake_response = FakeHttpResponse(lines=[
            "data: " + json.dumps({
                "event_type": "step.delta",
                "delta": {"type": "audio", "data": "not-base64"},
            }),
            "",
        ])
        with patch.object(chatbot, "API_KEY", "test-key"), patch.object(
            chatbot.httpx, "stream", return_value=FakeHttpStream(fake_response)
        ):
            response = self.client.post(
                "/api/speech",
                json={"text": "मराठी चाचणी.", "language": "mr"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"")

    def test_speech_rejects_invalid_gender(self):
        with patch.object(chatbot, "API_KEY", "test-key"), patch.object(
            chatbot.httpx, "stream"
        ) as post:
            response = self.client.post(
                "/api/speech",
                json={"text": "Hello.", "gender": "unknown"},
            )

        self.assertEqual(response.status_code, 400)
        post.assert_not_called()

    def test_speech_rejects_invalid_language(self):
        with patch.object(chatbot, "API_KEY", "test-key"), patch.object(
            chatbot.httpx, "stream"
        ) as post:
            response = self.client.post(
                "/api/speech",
                json={"text": "Hello.", "language": "unsupported"},
            )

        self.assertEqual(response.status_code, 400)
        post.assert_not_called()

    def test_speech_requires_api_key(self):
        with patch.object(chatbot, "API_KEY", ""), patch.object(
            chatbot.httpx, "stream"
        ) as post:
            response = self.client.post(
                "/api/speech",
                json={"text": "Hello.", "gender": "female"},
            )

        self.assertEqual(response.status_code, 500)
        self.assertIn("GEMINI_API_KEY", response.get_json()["error"])
        post.assert_not_called()

    def test_truncated_history_does_not_start_with_model(self):
        fake_models = FakeModels()
        fake_client = SimpleNamespace(models=fake_models)
        conversation = (
            [{"role": "user", "text": "First question."},
             {"role": "model", "text": "First answer."}] * 10
            + [{"role": "user", "text": "Latest question."}]
        )

        with patch.object(chatbot, "client", fake_client):
            response = self.client.post(
                "/api/chat",
                json={"messages": conversation},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_models.contents[0].role, "user")
        self.assertEqual(fake_models.contents[-1].parts[0].text, "Latest question.")

    def test_text_file_is_sent_as_prompt_context(self):
        fake_models = FakeModels()
        fake_client = SimpleNamespace(models=fake_models)

        with patch.object(chatbot, "client", fake_client):
            response = self.client.post(
                "/api/chat",
                data={
                    "messages": json.dumps([
                        {"role": "user", "text": "Explain this file."},
                    ]),
                    "files": (io.BytesIO(b"Java fundamentals"), "notes.txt"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("notes.txt", fake_models.contents[-1].parts[1].text)
        self.assertIn("Java fundamentals", fake_models.contents[-1].parts[1].text)

    def test_pdf_is_sent_as_inline_media(self):
        fake_models = FakeModels()
        fake_client = SimpleNamespace(models=fake_models)

        with patch.object(chatbot, "client", fake_client):
            response = self.client.post(
                "/api/chat",
                data={
                    "messages": json.dumps([
                        {"role": "user", "text": "Summarize this PDF."},
                    ]),
                    "files": (io.BytesIO(b"%PDF-example"), "chapter.pdf"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        media_part = fake_models.contents[-1].parts[1]
        self.assertEqual(media_part.inline_data.mime_type, "application/pdf")
        self.assertEqual(media_part.inline_data.data, b"%PDF-example")

    def test_unsupported_file_format_is_rejected(self):
        with patch.object(chatbot, "client", object()):
            response = self.client.post(
                "/api/chat",
                data={
                    "messages": json.dumps([
                        {"role": "user", "text": "Read this file."},
                    ]),
                    "files": (io.BytesIO(b"data"), "program.exe"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("unsupported format", response.get_json()["error"])

    def test_oversized_file_is_rejected(self):
        upload = FileStorage(
            stream=io.BytesIO(b"x" * (chatbot.MAX_FILE_SIZE + 1)),
            filename="notes.txt",
        )

        with self.assertRaisesRegex(ValueError, "8 MB per-file limit"):
            chatbot.upload_to_gemini_part(upload)

    def test_rejects_invalid_conversation(self):
        with patch.object(chatbot, "client", object()):
            response = self.client.post(
                "/api/chat",
                json={"messages": [{"role": "admin", "text": "Hello"}]},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid role", response.get_json()["error"])

    def test_missing_api_key_is_reported(self):
        with patch.object(chatbot, "client", None):
            response = self.client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "text": "Hello"}]},
            )

        self.assertEqual(response.status_code, 500)
        self.assertIn("GEMINI_API_KEY", response.get_json()["error"])

    def test_gemini_api_error_returns_safe_message(self):
        fake_models = FakeModels(
            error=errors.APIError(
                503,
                {"error": {"message": "internal provider detail"}},
            ),
        )
        fake_client = SimpleNamespace(models=fake_models)

        with patch.object(chatbot, "client", fake_client):
            with self.assertLogs(chatbot.app.logger, level="ERROR"):
                response = self.client.post(
                    "/api/chat",
                    json={"messages": [{"role": "user", "text": "Hello"}]},
                )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("internal provider detail", response.get_data(as_text=True))
        self.assertIn("temporarily unavailable", response.get_data(as_text=True))

    def test_gemini_timeout_has_actionable_message(self):
        fake_models = FakeModels(
            error=errors.APIError(
                504,
                {"error": {"message": "upstream timeout detail"}},
            ),
        )
        fake_client = SimpleNamespace(models=fake_models)

        with patch.object(chatbot, "client", fake_client):
            with self.assertLogs(chatbot.app.logger, level="ERROR"):
                response = self.client.post(
                    "/api/chat",
                    json={"messages": [{"role": "user", "text": "Hello"}]},
                )

        self.assertEqual(response.status_code, 200)
        self.assertIn("timed out", response.get_data(as_text=True))
        self.assertNotIn("upstream timeout detail", response.get_data(as_text=True))

    def test_network_error_returns_json_error(self):
        fake_models = FakeModels(
            error=chatbot.httpx.ConnectError("network detail"),
        )
        fake_client = SimpleNamespace(models=fake_models)

        with patch.object(chatbot, "client", fake_client):
            with self.assertLogs(chatbot.app.logger, level="ERROR"):
                response = self.client.post(
                    "/api/chat",
                    json={"messages": [{"role": "user", "text": "Hello"}]},
                )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Could not reach Gemini", response.get_data(as_text=True))
        self.assertNotIn("network detail", response.get_data(as_text=True))

    def test_streaming_network_error_returns_event(self):
        fake_models = FakeModels(
            error=chatbot.httpx.ConnectError("network detail"),
        )
        fake_client = SimpleNamespace(models=fake_models)

        with patch.object(chatbot, "client", fake_client):
            with self.assertLogs(chatbot.app.logger, level="ERROR"):
                response = self.client.post(
                    "/api/chat",
                    json={"messages": [{"role": "user", "text": "Hello"}]},
                )

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("event: error", body)
        self.assertIn("Could not reach Gemini", body)
        self.assertNotIn("network detail", body)

    def test_oversized_request_returns_json_error(self):
        with patch.object(chatbot, "client", object()):
            with patch.dict(chatbot.app.config, {"MAX_CONTENT_LENGTH": 256}):
                response = self.client.post(
                    "/api/chat",
                    json={"messages": [{"role": "user", "text": "x" * 512}]},
                )

        self.assertEqual(response.status_code, 413)
        self.assertIn("shorten your message", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()

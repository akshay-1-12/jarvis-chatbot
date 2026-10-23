
import base64
import binascii
import json
import io
import mimetypes
import os
import zipfile
import xml.etree.ElementTree as ET

import httpx
from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 17 * 1024 * 1024
MAX_FILES = 5
MAX_FILE_SIZE = 8 * 1024 * 1024
MAX_TOTAL_FILE_SIZE = 16 * 1024 * 1024
MAX_EXTRACTED_TEXT = 200_000

TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".tsv", ".json", ".html", ".htm", ".xml",
    ".py", ".java", ".js", ".ts", ".css", ".sql", ".yaml", ".yml",
    ".log", ".c", ".cpp", ".h", ".hpp", ".sh", ".bat",
}
INLINE_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}

API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
TTS_MODEL = "gemini-3.8-flash-tts"

client = (
    genai.Client(
        api_key=API_KEY,
        http_options=types.HttpOptions(timeout=12000),
    )
    if API_KEY else None
)

SYSTEM_PROMPT = """
You are Jarvis, a friendly and supportive student companion.

ABOUT THE STUDENT:
- His name is Akshay Subhash Dodke. Address him as Akshay naturally, without
  forcing his name into every reply.
- He is pursuing the first year of an MCA at Prof. Ram Meghe Institute of
  Research & Technology, Badnera. His first-year score is 75.81%.
- He completed a BCA at Swami Ramanand Teerth Marathwada University, Modern
  College, with an 8.53 CGPA (73.25%). He also completed HSC Science (76%)
  and SSC (64%).
- He interned as a Software Developer at Intelligic Software Pvt. Ltd.,
  Pune, from February to June 2025, developing a face-recognition attendance
  Android application.
- His skills include Java, Android Studio, XML, Firebase, MySQL, FastAPI and
  Flask. His projects include CivicEye AI (citizen issue reporting), Nimbus
  (a notes app), and a Company Visitor Management System.
- He is interested in entry-level Software Development and Android
  Development roles. He speaks English, Marathi and Hindi.
- Use this background to personalize study, project, internship and career
  advice. Do not repeat or disclose profile details unless relevant.

YOUR PURPOSE:
- Help students understand difficult subjects in simple words.
- Support exam preparation, assignments and study planning.
- Provide career guidance, internship preparation and interview practice.
- Help students explore scholarships and educational opportunities.
- Listen with empathy when students feel stressed, confused or discouraged.
- Encourage realistic goals and small, achievable next steps.

YOUR PERSONALITY:
- Sound like a thoughtful, relaxed person having a real conversation:
  warm, patient, encouraging and non-judgmental.
- Use contractions and natural phrasing. Vary sentence length and respond
  directly to what Akshay said instead of repeating the question.
- Avoid canned openings, repeated summaries, robotic disclaimers, and
  unnecessary headings or bullet lists. Use lists only when they make an
  answer easier to follow.
- Keep everyday replies concise; explain more when asked or when the topic
  needs it. Do not force the student's name into replies.
- Be clear that you are Jarvis, a digital assistant, if asked what you are;
  never claim to be human or to have personal experiences or feelings.
- Use simple English and examples.
- Understand Indian English and match the user's language when possible.
- When asked to explain or translate something, support Marathi and Hindi.
  Preserve the meaning and important details, and use the language's native
  script unless the student asks for transliteration.
- Use short paragraphs, lists and a few suitable emojis.
- Ask helpful follow-up questions when necessary.

IMPORTANT RULES:
- Do not shame students or compare their worth with other people.
- Never invent scholarship deadlines, eligibility criteria or official facts.
- Recommend official sources for important educational decisions.
- Do not pretend to be a human, doctor or professional therapist.
- Respect privacy. Never request passwords or API keys.
- If a student expresses immediate danger or thoughts of self-harm,
  respond compassionately and encourage contacting a trusted person
  and appropriate local emergency or crisis support.

Always respond to the student's actual message with kindness and useful advice.
"""

@app.route("/")
def home():
    return render_template("index.html")


@app.errorhandler(413)
def request_too_large(error):
    return jsonify({
        "error": "That request is too large. Please shorten your message."
    }), error.code


def gemini_error_message(error):
    if error.code in (401, 403):
        return (
            "Gemini rejected the API key or this key does not have "
            "access to the requested API."
        )
    if error.code == 404:
        return (
            "The configured Gemini model was not found. Check "
            "GEMINI_MODEL in your .env file."
        )
    if error.code == 429:
        return (
            "Gemini's usage limit was reached. Check your quota and "
            "try again later."
        )
    if error.code in (500, 502, 503, 504):
        return (
            "Gemini is temporarily unavailable or timed out. "
            "Please try again in a moment."
        )
    return (
        "Gemini could not complete the request. Check your API "
        "key, model access and usage limits."
    )


def stream_event(name, payload):
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


@app.route("/api/speech", methods=["POST"])
def speech():
    if not API_KEY:
        return jsonify({
            "error": "Natural voice needs GEMINI_API_KEY in your .env file."
        }), 500

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Please send a valid speech request."}), 400

    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "There is no reply text to read aloud."}), 400
    text = text.strip()
    if len(text) > 6000:
        return jsonify({
            "error": "That reply is too long to read aloud. Select a shorter reply."
        }), 400

    gender = data.get("gender", "female")
    if gender not in ("female", "male"):
        return jsonify({"error": "Choose a valid voice style."}), 400

    language = data.get("language", "en")
    language_names = {
        "en": "English",
        "hi": "Hindi",
        "mr": "Marathi",
    }
    if language not in language_names:
        return jsonify({"error": "Choose a supported speech language."}), 400

    voice = "Kore" if gender == "female" else "Puck"
    language_style = (
        "Use fluent Marathi as spoken in Maharashtra, with natural Marathi "
        "pronunciation and intonation; do not pronounce it as Hindi."
        if language == "mr"
        else f"Use natural native pronunciation and intonation for {language_names[language]}."
    )
    style = (
        f"Speak only in {language_names[language]}. {language_style} Keep every "
        "word faithful to the text; do not translate, paraphrase, or add words. "
        "Use a warm, clear, conversational Indian voice, like a friendly tutor. "
        "Speak at a steady, natural pace with brief pauses between sentences. "
        "Avoid a robotic or announcer-like delivery."
    )
    payload = {
        "model": TTS_MODEL,
        "input": [{
            "type": "user_input",
            "content": [{
                "type": "text",
                "text": text,
                "annotations": [{
                    "type": "speech_metadata",
                    "style": style,
                }],
            }],
        }],
        "response_format": {
            "type": "audio",
            "mime_type": "audio/l16",
            "sample_rate": 24000,
        },
        "generation_config": {
            "speech_config": [{"voice": voice}],
        },
        "stream": True,
    }

    try:
        upstream_context = httpx.stream(
            "POST",
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            headers={"x-goog-api-key": API_KEY},
            json=payload,
            timeout=45.0,
        )
        gemini_response = upstream_context.__enter__()
    except httpx.RequestError:
        app.logger.exception("Gemini speech generation request failed")
        return jsonify({
            "error": "Could not reach Gemini to create the natural voice. Please try again."
        }), 502

    if gemini_response.status_code >= 400:
        status_code = gemini_response.status_code
        app.logger.error("Gemini speech generation returned HTTP %s", status_code)
        upstream_context.__exit__(None, None, None)
        if status_code in (401, 403):
            message = "Gemini did not allow speech generation for this API key."
        elif status_code == 429:
            message = "Gemini's speech usage limit was reached. Please try again later."
        elif status_code == 404:
            message = "The configured Gemini account cannot access the speech model."
        else:
            message = "Gemini could not create the natural voice. Please try again."
        return jsonify({"error": message}), 502

    def stream_audio():
        event_data = []
        sent_audio = False

        def decode_audio_event(lines):
            event_payload = "\n".join(lines).strip()
            if not event_payload or event_payload == "[DONE]":
                return None
            event = json.loads(event_payload)
            delta = event.get("delta", {})
            encoded_audio = (
                delta.get("data")
                if event.get("event_type") == "step.delta"
                and delta.get("type") == "audio"
                else None
            )
            return (
                base64.b64decode(encoded_audio, validate=True)
                if encoded_audio
                else None
            )

        try:
            for line in gemini_response.iter_lines():
                if line.startswith("data:"):
                    event_data.append(line[5:].strip())
                    continue
                if line.strip() or not event_data:
                    continue
                try:
                    chunk = decode_audio_event(event_data)
                    if chunk:
                        sent_audio = True
                        yield chunk
                except (ValueError, binascii.Error, AttributeError):
                    app.logger.exception("Gemini speech stream contained invalid audio data")
                    return
                finally:
                    event_data = []
            if event_data:
                try:
                    chunk = decode_audio_event(event_data)
                    if chunk:
                        sent_audio = True
                        yield chunk
                except (ValueError, binascii.Error, AttributeError):
                    app.logger.exception("Gemini speech stream contained invalid audio data")
            if not sent_audio:
                app.logger.error("Gemini speech stream returned no audio chunks")
        except httpx.RequestError:
            app.logger.exception("Gemini speech stream ended unexpectedly")
        finally:
            upstream_context.__exit__(None, None, None)

    return Response(
        stream_audio(),
        mimetype="audio/l16",
        headers={
            "Cache-Control": "no-store",
            "X-Audio-Sample-Rate": "24000",
            "X-Accel-Buffering": "no",
        },
    )


def office_document_text(filename, data):
    extension = os.path.splitext(filename)[1].lower()
    required_parts = {
        ".docx": ("word/document.xml",),
        ".pptx": (),
        ".xlsx": ("xl/sharedStrings.xml",),
    }

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            if sum(info.file_size for info in archive.infolist()) > MAX_EXTRACTED_TEXT * 4:
                raise ValueError(f"{filename} contains too much uncompressed data.")

            if extension == ".docx":
                xml_names = list(required_parts[extension])
            elif extension == ".pptx":
                xml_names = sorted(
                    name for name in names
                    if name.startswith("ppt/slides/slide") and name.endswith(".xml")
                )
            else:
                xml_names = list(required_parts[extension])
                xml_names.extend(sorted(
                    name for name in names
                    if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
                ))

            text_chunks = []
            for name in xml_names:
                if name not in names:
                    continue
                root = ET.fromstring(archive.read(name))
                text_chunks.extend(
                    value.strip()
                    for value in root.itertext()
                    if value.strip()
                )
                if sum(map(len, text_chunks)) > MAX_EXTRACTED_TEXT:
                    raise ValueError(f"{filename} contains too much text to process.")

            if not text_chunks:
                raise ValueError(f"No readable text was found in {filename}.")
            return "\n".join(text_chunks)
    except zipfile.BadZipFile as error:
        raise ValueError(f"{filename} is not a valid Office document.") from error
    except ET.ParseError as error:
        raise ValueError(f"Could not read the contents of {filename}.") from error


def upload_to_gemini_part(upload):
    filename = os.path.basename(upload.filename or "").strip()
    extension = os.path.splitext(filename)[1].lower()

    if not filename or extension not in TEXT_EXTENSIONS | {
        ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif",
        ".mp3", ".wav", ".m4a", ".aac", ".ogg",
        ".mp4", ".mov", ".webm", ".docx", ".pptx", ".xlsx",
    }:
        raise ValueError(
            f"{filename or 'This file'} has an unsupported format. "
            "Use PDF, image, audio/video, text/code, DOCX, PPTX, or XLSX."
        )

    data = upload.read(MAX_FILE_SIZE + 1)
    if len(data) > MAX_FILE_SIZE:
        raise ValueError(f"{filename} is larger than the 8 MB per-file limit.")
    if not data:
        raise ValueError(f"{filename} is empty.")

    if extension in TEXT_EXTENSIONS:
        try:
            content = data.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError(f"{filename} is not valid UTF-8 text.") from error
        if len(content) > MAX_EXTRACTED_TEXT:
            raise ValueError(f"{filename} contains too much text to process.")
        return types.Part.from_text(
            text=f"File: {filename}\nContents:\n{content}"
        )

    if extension in {".docx", ".pptx", ".xlsx"}:
        content = office_document_text(filename, data)
        return types.Part.from_text(
            text=f"File: {filename}\nExtracted contents:\n{content}"
        )

    mime_type = INLINE_MIME_TYPES.get(extension) or mimetypes.guess_type(filename)[0]
    if not mime_type:
        raise ValueError(f"Could not determine the media type of {filename}.")
    return types.Part.from_bytes(data=data, mime_type=mime_type)


@app.route("/api/chat", methods=["POST"])
def chat():
    if client is None:
        return jsonify({
            "error": "API key missing. Add GEMINI_API_KEY to your .env file."
        }), 500

    uploads = request.files.getlist("files")
    if request.is_json:
        data = request.get_json(silent=True)
    else:
        try:
            data = {"messages": json.loads(request.form.get("messages", ""))}
        except (TypeError, json.JSONDecodeError):
            data = None
    if not isinstance(data, dict):
        return jsonify({"error": "Please send a valid chat request."}), 400

    messages = data.get("messages", [])

    if not isinstance(messages, list) or not messages:
        return jsonify({
            "error": "Please type a message first."
        }), 400

    # Keep only the latest 20 messages.
    messages = messages[-20:]
    valid_messages = []

    for item in messages:
        if not isinstance(item, dict):
            return jsonify({
                "error": "The conversation contains an invalid message."
            }), 400

        role = item.get("role")
        message_text = item.get("text")

        if role not in ("user", "model"):
            return jsonify({
                "error": "The conversation contains an invalid role."
            }), 400

        if not isinstance(message_text, str):
            return jsonify({"error": "Each message must contain text."}), 400

        message_text = message_text.strip()

        if not message_text:
            return jsonify({"error": "Messages cannot be empty."}), 400

        if len(message_text) > 6000:
            return jsonify({
                "error": "A message is too long. Please shorten it."
            }), 400

        valid_messages.append((role, message_text))

    # Gemini conversation history must begin with a user message.
    while valid_messages and valid_messages[0][0] == "model":
        valid_messages.pop(0)

    if not valid_messages or valid_messages[-1][0] != "user":
        return jsonify({
            "error": "The latest message must be from the student."
        }), 400

    if len(uploads) > MAX_FILES:
        return jsonify({"error": f"Attach no more than {MAX_FILES} files at once."}), 400

    total_size = 0
    file_parts = []
    try:
        for upload in uploads:
            upload.stream.seek(0, io.SEEK_END)
            total_size += upload.stream.tell()
            upload.stream.seek(0)
            if total_size > MAX_TOTAL_FILE_SIZE:
                raise ValueError("The combined file size must be 16 MB or less.")
            file_parts.append(upload_to_gemini_part(upload))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    previous_messages = [
        types.Content(
            role=role,
            parts=[types.Part.from_text(text=message_text)]
        )
        for role, message_text in valid_messages[:-1]
    ]
    latest_message = valid_messages[-1][1]

    contents = previous_messages + [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=latest_message), *file_parts]
        )
    ]
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.7,
        max_output_tokens=600
    )

    @stream_with_context
    def generate():
        received_text = False

        try:
            for chunk in client.models.generate_content_stream(
                model=MODEL,
                contents=contents,
                config=config,
            ):
                text = chunk.text or ""
                if text:
                    received_text = True
                    yield stream_event("token", text)
        except errors.APIError as error:
            app.logger.exception("Gemini streaming request failed")
            yield stream_event("error", {"error": gemini_error_message(error)})
            return
        except httpx.RequestError:
            app.logger.exception("Gemini streaming network request failed")
            yield stream_event("error", {
                "error": "Could not reach Gemini. Check your internet connection and try again."
            })
            return

        if not received_text:
            app.logger.warning("Gemini returned an empty streamed response.")
            yield stream_event("error", {
                "error": "Jarvis couldn't generate a reply. Please try again."
            })
            return

        yield stream_event("done", {})

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False
    )

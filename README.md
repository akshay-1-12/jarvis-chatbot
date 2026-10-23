# Jarvis Student Support

Jarvis is a student-support chatbot built with Flask and the Google Gemini API.

## Run locally

1. Install Python 3.10 or newer.
2. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Add your Gemini API key to `.env`:

   ```dotenv
   GEMINI_API_KEY=your_api_key
   GEMINI_MODEL=gemini-3.5-flash-lite
   ```

5. Start the app:

   ```powershell
   python app.py
   ```

6. Open <http://127.0.0.1:5000>.

Keep `.env` private. The `.gitignore` file excludes it from Git.

Jarvis has a local student profile in `app.py` to personalize study and career
advice. Contact details are intentionally not included in the Gemini prompt.

## Files, microphone and voice

- Attach up to 5 files, with an 8 MB per-file and 16 MB combined limit.
- Supported inputs: PDF; PNG, JPEG, WebP and GIF; MP3, WAV, M4A, AAC and OGG;
  MP4, MOV and WebM; plain text, common code and data files; DOCX, PPTX and XLSX.
- Files are sent to Gemini for the current conversation and are not saved by
  this app. Re-attached conversation files are resent with each question so
  follow-up questions can refer to them.
- Microphone dictation uses the browser's speech-recognition support and
  requires microphone permission. Availability varies by browser.
- The side panel's language control asks Jarvis to explain the latest answer
  or attached file in Marathi, Hindi, or English. On narrower screens, the
  same control appears above the chat and also sets the microphone dictation
  language when browser speech recognition supports it.
- Each Jarvis reply has its own read/pause/resume and stop controls. Replies
  remain text-only unless you start reading manually.
- Read-aloud uses Gemini 3.8 Flash TTS for higher-fidelity narration and
  regional pronunciation. It makes an additional Gemini API request each time
  and may use more quota than the Lite model; check Google's current pricing
  and usage limits. If that
  request is unavailable, the app falls back to the selected browser/device
  voice; available fallback voices vary by device and language.

## Run tests

```powershell
python -m unittest discover -s tests -v
```

The chat endpoint tests use a mocked Gemini client, so they do not make API
requests or consume API quota.

Voice style and device fallback voice changes are applied only after pressing
**OK** in Settings; closing the dialog without applying discards pending
changes.

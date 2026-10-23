
const messagesEl = document.getElementById("messages");
const input = document.getElementById("userInput");
const form = document.getElementById("chatForm");
const sendBtn = document.getElementById("sendBtn");
const typing = document.getElementById("typing");
const welcome = document.getElementById("welcome");
const quickPanel = document.getElementById("quickPanel");
const clearChat = document.getElementById("clearChat");
const connectionStatus = document.getElementById("connectionStatus");
const fileInput = document.getElementById("fileInput");
const attachButton = document.getElementById("attachButton");
const attachmentList = document.getElementById("attachmentList");
const micButton = document.getElementById("micButton");
const settingsButton = document.getElementById("settingsButton");
const settingsDialog = document.getElementById("voiceSettings");
const voiceGender = document.getElementById("voiceGender");
const voiceChoice = document.getElementById("voiceChoice");

let history = [];
let busy = false;
let selectedFiles = [];
let recognition = null;
let speechVoices = [];
let activeUtterance = null;
let activeReadButton = null;
let activeAudioContext = null;
let activeAudioSources = new Set();
let speechRequest = null;
let readingState = "read";

const MAX_FILES = 5;
const MAX_FILE_SIZE = 8 * 1024 * 1024;
const MAX_TOTAL_FILE_SIZE = 16 * 1024 * 1024;
let settings = {};
try {
    const savedSettings = JSON.parse(
        localStorage.getItem("jarvisVoiceSettings") || "{}"
    );
    if (savedSettings && typeof savedSettings === "object") {
        settings = savedSettings;
    }
} catch (error) {
    console.warn("Could not read saved voice settings.", error);
}
voiceGender.value = settings.gender === "male" ? "male" : "female";
const languageSelectors = [
    ...document.querySelectorAll(".explain-language"),
];
let preferredSpeechLanguage = ["mr", "hi", "en"].includes(settings.explainLanguage)
    ? settings.explainLanguage
    : "mr";
function updateRecognitionLanguage() {
    if (!recognition) return;
    recognition.lang = {
        mr: "mr-IN",
        hi: "hi-IN",
        en: "en-IN",
    }[preferredSpeechLanguage] || "en-IN";
}

languageSelectors.forEach(selector => {
    selector.value = ["mr", "hi", "en"].includes(settings.explainLanguage)
        ? settings.explainLanguage
        : "mr";
    selector.addEventListener("change", () => {
        settings.explainLanguage = selector.value;
        preferredSpeechLanguage = selector.value;
        languageSelectors.forEach(otherSelector => {
            otherSelector.value = selector.value;
        });
        updateRecognitionLanguage();
        saveVoiceSettings();
    });
});

function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

function showConversation() {
    welcome.hidden = true;
    quickPanel.hidden = true;
}

function showHome() {
    welcome.hidden = false;
    quickPanel.hidden = false;
}

function addMessage(role, text) {
    showConversation();

    const row = document.createElement("div");
    row.className = `message ${role === "user" ? "user" : "bot"}`;

    const avatar = document.createElement("div");
    avatar.className = `avatar${role === "user" ? "" : " jarvis-avatar"}`;
    if (role === "user") {
        avatar.textContent = "Y";
    } else {
        const face = document.createElement("span");
        face.className = "robot-face";
        face.setAttribute("aria-label", "Jarvis robot");

        for (const partClass of [
            "robot-antenna",
            "robot-eye",
            "robot-eye",
            "robot-mouth",
        ]) {
            const part = document.createElement("span");
            part.className = partClass;
            face.appendChild(part);
        }

        avatar.appendChild(face);
    }
    avatar.setAttribute(
        "aria-label",
        role === "user" ? "You" : "Jarvis"
    );

    const bubble = document.createElement("div");
    bubble.className = "bubble";

    // Keep replies as plain text for safety.
    bubble.textContent = text;

    const content = document.createElement("div");
    content.className = "message-content";
    content.appendChild(bubble);
    if (role !== "user") {
        const controls = document.createElement("div");
        controls.className = "message-reading-controls";

        const toggle = document.createElement("button");
        toggle.className = "reading-toggle";
        toggle.type = "button";
        toggle.dataset.readingToggle = "";
        toggle.setAttribute("aria-label", "Read this reply aloud");
        const icon = document.createElement("span");
        icon.className = "reading-control-icon";
        icon.textContent = "▶";
        const label = document.createElement("span");
        label.className = "reading-control-label";
        label.textContent = "Read reply";
        toggle.append(icon, label);
        toggle.addEventListener("click", () => toggleMessageReading(toggle));

        const stop = document.createElement("button");
        stop.className = "reading-stop";
        stop.type = "button";
        stop.dataset.readingStop = "";
        stop.textContent = "■ Stop";
        stop.setAttribute("aria-label", "Stop reading this reply");
        stop.disabled = true;
        stop.addEventListener("click", stopReading);

        controls.append(toggle, stop);
        content.appendChild(controls);
    }

    row.append(avatar, content);
    messagesEl.appendChild(row);

    scrollToBottom();
    return bubble;
}

function saveVoiceSettings() {
    localStorage.setItem("jarvisVoiceSettings", JSON.stringify({
        gender: settings.gender === "male" ? "male" : "female",
        voice: settings.voice || "",
        explainLanguage: languageSelectors[0]?.value || "mr",
    }));
}

function updateVoiceChoices() {
    if (!("speechSynthesis" in window)) return;

    const previousVoice = settings.voice || voiceChoice.value;
    speechVoices = window.speechSynthesis.getVoices();
    const genderNames = voiceGender.value === "female"
        ? /female|woman|zira|aria|jenny|susan|samantha|karen|siri|heera/i
        : /male|man|david|mark|guy|daniel|alex|tom|fred|ravi/i;
    const preferredVoices = speechVoices.filter(voice => genderNames.test(voice.name));
    const matchingVoices = preferredVoices.length ? preferredVoices : speechVoices;
    const languageVoices = speechVoices.filter(voice =>
        /^(en|hi|mr)/i.test(voice.lang)
    );
    const voicesToShow = languageVoices.length ? languageVoices : matchingVoices;

    voiceChoice.replaceChildren(new Option("System default", ""));
    voicesToShow.forEach(voice => {
        voiceChoice.add(new Option(
            `${voice.name} (${voice.lang})`,
            voice.voiceURI
        ));
    });
    if ([...voiceChoice.options].some(option => option.value === previousVoice)) {
        voiceChoice.value = previousVoice;
    }
}

function setReadButton(button, state) {
    const controls = {
        read: ["▶", "Read reply", "Read this reply aloud"],
        pause: ["⏸", "Pause reading", "Pause reading"],
        resume: ["▶", "Resume reading", "Resume reading"],
        loading: ["…", "Preparing voice…", "Preparing natural voice"],
    };
    const [symbol, label, ariaLabel] = controls[state];
    readingState = state;
    if (!button) return;
    const icon = button.querySelector(".reading-control-icon");
    const text = button.querySelector(".reading-control-label");
    if (icon) icon.textContent = symbol;
    if (text) text.textContent = label;
    button.title = ariaLabel;
    button.setAttribute("aria-label", ariaLabel);
    button.classList.toggle("reading", state === "pause" || state === "loading");
    const stopButton = button.closest(".message-reading-controls")
        ?.querySelector("[data-reading-stop]");
    if (stopButton) stopButton.disabled = state === "read";
}

function playDeviceVoice(text, button, language) {
    if (!("speechSynthesis" in window)) {
        connectionStatus.textContent = "Speech is unavailable on this device";
        setReadButton(button, "read");
        activeReadButton = null;
        return false;
    }

    const utterance = new SpeechSynthesisUtterance(text);
    const speechLanguage = ["mr", "hi", "en"].includes(language)
        ? language
        : "en";
    const localePrefix = speechLanguage;
    const localeNames = {
        mr: "Marathi",
        hi: "Hindi",
        en: "English",
    };
    utterance.lang = speechLanguage === "mr"
        ? "mr-IN"
        : speechLanguage === "hi"
            ? "hi-IN"
            : "en-IN";
    utterance.pitch = 1;
    utterance.rate = 1;

    const selectedVoice = speechVoices.find(
        voice => voice.voiceURI === voiceChoice.value
    );
    const localeVoices = speechVoices.filter(
        voice => voice.lang.toLowerCase().startsWith(localePrefix)
    );
    const genderNames = voiceGender.value === "female"
        ? /female|woman|zira|aria|jenny|susan|samantha|karen|siri|heera/i
        : /male|man|david|mark|guy|daniel|alex|tom|fred|ravi/i;
    const naturalVoiceNames = /natural|neural|online|premium/i;
    const rankedLocaleVoices = [...localeVoices].sort((first, second) => {
        const score = voice =>
            (naturalVoiceNames.test(voice.name) ? 3 : 0) +
            (genderNames.test(voice.name) ? 1 : 0);
        return score(second) - score(first);
    });
    const matchingSelectedVoice = selectedVoice &&
        selectedVoice.lang.toLowerCase().startsWith(localePrefix)
        ? selectedVoice
        : null;
    utterance.voice = matchingSelectedVoice || rankedLocaleVoices[0] || null;
    if (!utterance.voice) {
        connectionStatus.textContent =
            `No ${localeNames[speechLanguage]} device voice is available`;
        setReadButton(button, "read");
        activeReadButton = null;
        return false;
    }
    activeUtterance = utterance;
    utterance.onend = () => finishReading(utterance);
    utterance.onerror = () => finishReading(utterance);
    window.speechSynthesis.speak(utterance);
    setReadButton(button, "pause");
    connectionStatus.textContent = "Reading aloud with device voice";
    return true;
}

function prepareAudioContext() {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return null;

    try {
        const context = new AudioContextClass({ sampleRate: 24000 });
        activeAudioContext = context;
        if (context.state === "suspended") {
            context.resume().catch(error => {
                if (activeAudioContext === context) {
                    console.warn("Could not prepare audio playback.", error);
                }
            });
        }
        return context;
    } catch (error) {
        console.warn("Could not prepare audio playback.", error);
        return null;
    }
}

async function speakText(
    text,
    button,
    language = preferredSpeechLanguage,
    preparedAudioContext = null
) {
    if (preparedAudioContext) {
        if (activeAudioContext !== preparedAudioContext) return;
    } else {
        stopReading();
    }
    activeReadButton = button;
    setReadButton(button, "loading");
    connectionStatus.textContent = "Connecting to natural voice";
    const controller = new AbortController();
    speechRequest = controller;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;

    try {
        if (!AudioContextClass) {
            throw new Error("Streaming audio is not supported by this browser.");
        }
        activeAudioContext = preparedAudioContext ||
            new AudioContextClass({ sampleRate: 24000 });
        if (activeAudioContext.state === "suspended") {
            await activeAudioContext.resume();
        }

        const response = await fetch("/api/speech", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                text,
                gender: voiceGender.value,
                language,
            }),
            signal: controller.signal,
        });
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error || `Speech request failed (${response.status})`);
        }

        if (speechRequest !== controller) return;
        const played = await streamPcmAudio(response, button, controller);
        if (speechRequest !== controller) return;
        if (!played) {
            throw new Error("Gemini did not return any audio.");
        }
    } catch (error) {
        if (error.name === "AbortError") return;
        console.warn("Gemini natural voice failed; using the device voice.", error);
        speechRequest = null;
        if (activeAudioContext) {
            const context = activeAudioContext;
            activeAudioContext = null;
            activeAudioSources.clear();
            await context.close().catch(() => {});
        }
        const fallbackStarted = playDeviceVoice(text, button, language);
        if (fallbackStarted && activeUtterance && activeReadButton === button) {
            connectionStatus.textContent =
                "Gemini voice unavailable; using device voice";
            button.title = `Device voice fallback: ${error.message}`;
            button.setAttribute("aria-label", "Reading with device voice fallback");
        } else if (!fallbackStarted) {
            const languageNames = {
                mr: "Marathi",
                hi: "Hindi",
                en: "English",
            };
            connectionStatus.textContent =
                `Natural ${languageNames[language] || "speech"} voice failed, ` +
                "and no matching device voice is available";
            button.title = error.message;
        }
    }
}

async function streamPcmAudio(response, button, controller) {
    if (!response.body) {
        throw new Error("The browser did not provide a readable audio stream.");
    }
    const context = activeAudioContext;
    const reader = response.body.getReader();
    let carryByte = null;
    let nextStartTime = context.currentTime + 0.08;
    let sourceCount = 0;
    let receivedAudio = false;
    let streamFinished = false;

    function queuePcmBytes(bytes) {
        let pcmBytes = bytes;
        if (carryByte !== null) {
            const combined = new Uint8Array(bytes.length + 1);
            combined[0] = carryByte;
            combined.set(bytes, 1);
            pcmBytes = combined;
            carryByte = null;
        }
        if (pcmBytes.length % 2) {
            carryByte = pcmBytes[pcmBytes.length - 1];
            pcmBytes = pcmBytes.subarray(0, pcmBytes.length - 1);
        }
        if (!pcmBytes.length) return;

        const samples = new Float32Array(pcmBytes.length / 2);
        const view = new DataView(
            pcmBytes.buffer,
            pcmBytes.byteOffset,
            pcmBytes.byteLength
        );
        for (let index = 0; index < samples.length; index += 1) {
            samples[index] = view.getInt16(index * 2, true) / 32768;
        }

        const audioBuffer = context.createBuffer(1, samples.length, 24000);
        audioBuffer.copyToChannel(samples, 0);
        const source = context.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(context.destination);
        const startTime = Math.max(nextStartTime, context.currentTime + 0.025);
        nextStartTime = startTime + audioBuffer.duration;
        sourceCount += 1;
        receivedAudio = true;
        activeAudioSources.add(source);
        source.onended = () => {
            activeAudioSources.delete(source);
            source.disconnect();
            sourceCount -= 1;
            if (streamFinished && sourceCount === 0) {
                finishAudioReading(context);
            }
        };
        source.start(startTime);
        if (activeReadButton === button && sourceCount === 1) {
            setReadButton(button, "pause");
            connectionStatus.textContent = "Reading aloud";
        }
    }

    while (true) {
        const { value, done } = await reader.read();
        if (speechRequest !== controller) return false;
        if (value?.length) queuePcmBytes(value);
        if (done) break;
    }

    streamFinished = true;
    if (carryByte !== null) {
        console.warn("Gemini speech stream ended with an incomplete PCM sample.");
    }
    if (sourceCount === 0 && activeAudioContext === context) {
        finishAudioReading(context);
    }
    return receivedAudio;
}

function finishReading(utterance) {
    if (activeUtterance !== utterance) return;
    activeUtterance = null;
    setReadButton(activeReadButton, "read");
    activeReadButton = null;
    connectionStatus.textContent = "Online";
}

function finishAudioReading(context) {
    if (activeAudioContext !== context) return;
    activeAudioContext = null;
    activeAudioSources.clear();
    setReadButton(activeReadButton, "read");
    activeReadButton = null;
    speechRequest = null;
    context.close().catch(() => {});
    connectionStatus.textContent = "Online";
}

function stopReading() {
    if ("speechSynthesis" in window) {
        window.speechSynthesis.cancel();
    }
    if (speechRequest) {
        speechRequest.abort();
        speechRequest = null;
    }
    if (activeAudioContext) {
        activeAudioSources.forEach(source => {
            try {
                source.stop();
                source.disconnect();
            } catch (error) {
                if (error.name !== "InvalidStateError") throw error;
            }
        });
        activeAudioSources.clear();
        const context = activeAudioContext;
        activeAudioContext = null;
        context.close().catch(() => {});
    }
    setReadButton(activeReadButton, "read");
    activeReadButton = null;
    activeUtterance = null;
    connectionStatus.textContent = "Online";
}

function toggleMessageReading(button) {
    if (activeReadButton === button && readingState !== "read") {
        if (activeAudioContext) {
            if (activeAudioContext.state === "suspended") {
                activeAudioContext.resume().then(() => {
                    setReadButton(button, "pause");
                    connectionStatus.textContent = "Reading aloud";
                }).catch(() => {
                    connectionStatus.textContent = "Could not resume audio";
                });
            } else {
                activeAudioContext.suspend();
                setReadButton(button, "resume");
                connectionStatus.textContent = "Reading paused";
            }
        } else if ("speechSynthesis" in window && window.speechSynthesis.paused) {
            window.speechSynthesis.resume();
            setReadButton(button, "pause");
            connectionStatus.textContent = "Reading aloud";
        } else if ("speechSynthesis" in window && window.speechSynthesis.speaking) {
            window.speechSynthesis.pause();
            setReadButton(button, "resume");
            connectionStatus.textContent = "Reading paused";
        }
        return;
    }

    const replyText = button.closest(".message")
        ?.querySelector(".bubble")?.textContent.trim();
    if (!replyText) {
        connectionStatus.textContent = "There is no reply to read";
        return;
    }
    const language = preferredSpeechLanguage;
    const containsDevanagari = /[\u0900-\u097F]/.test(replyText);
    if (language === "en" && !containsDevanagari) {
        speakText(replyText, button, language);
        return;
    }
    if (containsDevanagari) {
        const spokenLanguage = ["mr", "hi"].includes(language) ? language : "mr";
        speakText(replyText, button, spokenLanguage);
        return;
    }
    const languageNames = {
        mr: "Marathi",
        hi: "Hindi",
    };
    if (busy) {
        connectionStatus.textContent =
            "Wait for Jarvis to finish before translating this reply";
        return;
    }
    stopReading();
    const preparedAudioContext = prepareAudioContext();
    sendMessage(
        `Translate this Jarvis reply into natural, easy-to-understand ` +
        `${languageNames[language]}. Preserve its meaning and details, and ` +
        `reply only with the translation:\n\n${replyText}`,
        { readAloud: true, language, preparedAudioContext }
    );
}

function explainLatestInSelectedLanguage(options = {}) {
    if (busy) return;
    const language = options.language || languageSelectors[0]?.value || "mr";
    preferredSpeechLanguage = language;
    const languageNames = {
        mr: "Marathi",
        hi: "Hindi",
        en: "English",
    };
    if (!history.length && !selectedFiles.length) {
        connectionStatus.textContent = "Ask a question or attach a file first";
        return;
    }
    sendMessage(
        `Please explain the latest answer and any attached file in natural, ` +
        `easy-to-understand ${languageNames[language]}. Translate the meaning ` +
        `accurately, preserve important details, and explain difficult words ` +
        `simply. Reply in ${languageNames[language]} using a warm, conversational ` +
        `tone. Do not add information that is not supported by the conversation ` +
        `or file.`,
        { readAloud: options.readAloud === true, language }
    );
}

document.querySelectorAll("[data-explain]").forEach(button => {
    button.addEventListener("click", explainLatestInSelectedLanguage);
});

function renderAttachments() {
    attachmentList.replaceChildren();
    attachmentList.hidden = selectedFiles.length === 0;

    selectedFiles.forEach((file, index) => {
        const chip = document.createElement("div");
        chip.className = "attachment-chip";
        const name = document.createElement("span");
        name.textContent = `${file.name} · ${(file.size / (1024 * 1024)).toFixed(1)} MB`;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "×";
        remove.setAttribute("aria-label", `Remove ${file.name}`);
        remove.addEventListener("click", () => {
            selectedFiles.splice(index, 1);
            renderAttachments();
        });
        chip.append(name, remove);
        attachmentList.appendChild(chip);
    });
}

async function sendMessage(message, options = {}) {
    message = message.trim();
    if (!message && selectedFiles.length) {
        message = "Please read and explain the attached file(s).";
    }

    if (!message || busy) return;

    busy = true;
    sendBtn.disabled = true;
    input.value = "";
    input.style.height = "auto";

    addMessage("user", message);

    history.push({
        role: "user",
        text: message
    });

    typing.hidden = false;
    connectionStatus.textContent = "Processing";

    let reply = "";
    let replyBubble = null;
    let audioContextTransferred = false;

    try {
        const body = new FormData();
        body.append("messages", JSON.stringify(history.slice(-20)));
        selectedFiles.forEach(file => body.append("files", file, file.name));

        const response = await fetch("/api/chat", {
            method: "POST",
            body
        });

        if (!response.ok) {
            const data = await response.json();
            throw new Error(
                data.error || `Request failed (${response.status})`
            );
        }

        if (!response.headers.get("content-type")?.includes("text/event-stream")) {
            const data = await response.json();
            reply = typeof data.reply === "string" ? data.reply : "";
            if (!reply.trim()) {
                throw new Error("Jarvis returned an empty reply. Please retry.");
            }
            replyBubble = addMessage("model", reply);
        } else {
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            let completed = false;

            function handleEvent(frame) {
                let eventName = "message";
                const dataLines = [];

                for (const line of frame.split("\n")) {
                    if (line.startsWith("event:")) {
                        eventName = line.slice(6).trim();
                    } else if (line.startsWith("data:")) {
                        dataLines.push(line.slice(5).trim());
                    }
                }

                if (!dataLines.length) return;

                const data = JSON.parse(dataLines.join("\n"));
                if (eventName === "token") {
                    reply += data;
                    if (!replyBubble) {
                        replyBubble = addMessage("model", "", false);
                    }
                    replyBubble.textContent += data;
                    scrollToBottom();
                } else if (eventName === "error") {
                    throw new Error(data.error || "Jarvis could not respond.");
                } else if (eventName === "done") {
                    completed = true;
                }
            }

            while (true) {
                const { value, done } = await reader.read();
                buffer += decoder.decode(value, { stream: !done });

                let boundary = buffer.indexOf("\n\n");
                while (boundary !== -1) {
                    handleEvent(buffer.slice(0, boundary));
                    buffer = buffer.slice(boundary + 2);
                    boundary = buffer.indexOf("\n\n");
                }

                if (done) break;
            }

            if (buffer.trim()) {
                handleEvent(buffer);
            }
            if (!completed) {
                throw new Error("The response ended before Jarvis finished. Please retry.");
            }
        }

        history.push({
            role: "model",
            text: reply
        });

        if (options.readAloud && replyBubble) {
            const readButton = replyBubble.closest(".message")
                ?.querySelector("[data-reading-toggle]");
            audioContextTransferred = Boolean(options.preparedAudioContext);
            speakText(
                reply,
                readButton,
                options.language,
                options.preparedAudioContext
            );
        } else if (!activeAudioContext && !activeUtterance) {
            connectionStatus.textContent = "Online";
        }

    } catch (error) {
        // Remove the unanswered message from the API history.
        history.pop();

        const errorMessage =
            "I'm sorry, I couldn't complete that request. 💙\n\n" +
            error.message +
            "\n\nPlease check your connection or try again.";
        if (replyBubble) {
            replyBubble.textContent += "\n\n" + errorMessage;
        } else {
            addMessage("model", errorMessage);
        }

        connectionStatus.textContent = "Check connection";

    } finally {
        if (
            options.preparedAudioContext &&
            !audioContextTransferred &&
            activeAudioContext === options.preparedAudioContext
        ) {
            activeAudioContext = null;
            options.preparedAudioContext.close().catch(error => {
                console.warn("Could not close unused audio context.", error);
            });
        }
        typing.hidden = true;
        busy = false;
        sendBtn.disabled = false;
        input.focus();
    }
}

form.addEventListener("submit", function(event) {
    event.preventDefault();
    sendMessage(input.value);
});

attachButton.addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", () => {
    const incomingFiles = [...fileInput.files];
    fileInput.value = "";

    if (selectedFiles.length + incomingFiles.length > MAX_FILES) {
        connectionStatus.textContent = `Attach up to ${MAX_FILES} files`;
        return;
    }
    if (incomingFiles.some(file => file.size > MAX_FILE_SIZE)) {
        connectionStatus.textContent = "Each file must be 8 MB or less";
        return;
    }
    const combinedSize = [
        ...selectedFiles,
        ...incomingFiles,
    ].reduce((total, file) => total + file.size, 0);
    if (combinedSize > MAX_TOTAL_FILE_SIZE) {
        connectionStatus.textContent = "Files must total 16 MB or less";
        return;
    }

    selectedFiles.push(...incomingFiles);
    renderAttachments();
    connectionStatus.textContent = "Files ready";
});

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.interimResults = true;
    recognition.continuous = false;
    updateRecognitionLanguage();

    let dictatedText = "";
    recognition.onstart = () => {
        dictatedText = "";
        micButton.classList.add("recording");
        micButton.setAttribute("aria-label", "Stop recording");
        connectionStatus.textContent = "Listening";
    };
    recognition.onresult = event => {
        dictatedText = [...event.results]
            .map(result => result[0].transcript)
            .join(" ")
            .trim();
        input.value = dictatedText;
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 120) + "px";
    };
    recognition.onerror = event => {
        connectionStatus.textContent = event.error === "not-allowed"
            ? "Allow microphone access"
            : "Microphone unavailable";
    };
    recognition.onend = () => {
        micButton.classList.remove("recording");
        micButton.setAttribute("aria-label", "Speak your message");
        if (dictatedText) {
            input.value = "";
            sendMessage(dictatedText);
        } else if (connectionStatus.textContent === "Listening") {
            connectionStatus.textContent = "Online";
        }
    };
}

micButton.addEventListener("click", () => {
    if (!recognition) {
        connectionStatus.textContent = "Speech input is unsupported";
        return;
    }
    if (busy) return;

    if (micButton.classList.contains("recording")) {
        recognition.stop();
    } else {
        try {
            recognition.start();
        } catch (error) {
            connectionStatus.textContent = "Microphone is already active";
        }
    }
});

settingsButton.addEventListener("click", () => {
    voiceGender.value = settings.gender === "male" ? "male" : "female";
    updateVoiceChoices();
    voiceChoice.value = settings.voice || "";
    settingsDialog.returnValue = "cancel";
    settingsDialog.showModal();
});
settingsDialog.querySelector(".settings-close").addEventListener("click", () => {
    settingsDialog.close("cancel");
});
settingsDialog.addEventListener("close", () => {
    if (settingsDialog.returnValue === "apply") {
        settings.gender = voiceGender.value;
        settings.voice = voiceChoice.value;
        saveVoiceSettings();
        return;
    }

    voiceGender.value = settings.gender === "male" ? "male" : "female";
    updateVoiceChoices();
    voiceChoice.value = settings.voice || "";
});
voiceGender.addEventListener("change", () => {
    updateVoiceChoices();
});

if ("speechSynthesis" in window) {
    updateVoiceChoices();
    window.speechSynthesis.addEventListener("voiceschanged", updateVoiceChoices);
}

input.addEventListener("keydown", function(event) {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMessage(input.value);
    }
});

input.addEventListener("input", function() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
});

// Quick-access cards and sidebar tools.
document.addEventListener("click", function(event) {
    const button = event.target.closest("[data-prompt]");

    if (button && !busy) {
        sendMessage(button.dataset.prompt);
        return;
    }

    const navButton = event.target.closest("[data-view]");

    if (!navButton || busy) return;

    document.querySelectorAll(".nav-item").forEach(item => {
        item.classList.remove("active");
    });

    navButton.classList.add("active");

    if (navButton.dataset.view === "home") {
        showHome();
    } else if (navButton.dataset.view === "chat") {
        input.focus();
    }
});

// Clear messages and begin a new conversation.
clearChat.addEventListener("click", function() {
    if (busy) return;

    history = [];
    messagesEl.replaceChildren();
    selectedFiles = [];
    renderAttachments();
    stopReading();

    showHome();

    connectionStatus.textContent = "Online";
    input.value = "";
    input.style.height = "auto";
    input.focus();

    document.querySelectorAll(".nav-item").forEach(item => {
        item.classList.remove("active");
    });

    document.querySelector('[data-view="home"]')
        ?.classList.add("active");
});

// Initially focus on the welcome screen.
showHome();

import flet as ft
import requests
import speech_recognition as sr
import threading
import asyncio
import edge_tts
import os
import re
import tempfile
import webbrowser
import subprocess
import random
import ctypes
from datetime import datetime
from urllib.parse import quote_plus

# ---------------- SETTINGS ----------------
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
VOICE = "en-US-GuyNeural"   # English male voice
MIC_DEVICE = None           # None = use your Windows default microphone
SPEECH_LANGUAGE = "en-US"

# ---------------- APP STATE ----------------
is_listening = False
listener_thread = None
page_ref = None
status_ref = None
conversation_ref = None
recognizer = sr.Recognizer()
recognizer.dynamic_energy_threshold = True
recognizer.pause_threshold = 0.55
recognizer.operation_timeout = 8

JOKES = [
    'Programmer ki biwi boli: “Sun rahe ho?” Programmer bola: “Haan, bas tumhari awaaz background process mein chal rahi hai!”',
    'Programmer ne kaha: “Meri zindagi mein bohot bugs hain.” Dost bola: “To phir girlfriend kyun dhoond rahe ho, pehle debugging kar lo!”',
    'Teacher: “Computer ka dimaagh kahan hota hai?” Student: “CPU mein.” Teacher: “Aur tumhara?” Student: “Sir, abhi loading chal rahi hai!”',
    'Programmer ki shaadi kyun nahi ho rahi thi? Har rishtay mein pehle compatibility test karta tha!',
    'Computer thanda kyun ho gaya? Usne Windows khuli chhor di thi!',
    'Programmer ne chai kyun nahi pi? Uski cup wali application crash ho gayi thi!',
    'Python programmer saanp ko dekh kar bola: “Bhai, tum real Python ho ya bas snake wali library?”',
    'Programmer ka favourite nashta kya hai? Java ke saath toast, aur bugs ke saath roast!',
    'Code chal hi nahi raha tha. Programmer ne computer ko kaha: “Bhai, meri izzat ka sawal hai!” Computer bola: “Meri bhi, is liye error dikha raha hoon!”',
    'Programmer late kyun aaya? Uska alarm loop mein phans gaya tha!',
    'Programmer ki jeb khaali kyun thi? Saara paisa cache mein tha, lekin cache clear ho gayi!',
    'Do programmers mile. Ek bola: “Tumhari life kaisi hai?” Doosra: “404: Happiness not found!”',
    'Programmer ne apni crush ko message bheja: “You had me at hello world.” Crush boli: “Sorry, main Java use karti hoon!”',
    'Computer doctor ke paas kyun gaya? Usko virus tha, aur antivirus ki appointment full thi!',
    'Programmer ne fridge kyun khola? Dekhna tha ke andar koi fresh code pada hai ya nahi!',
    'Programmer ka favourite gaana? “We will, we will debug you!”',
    'Programmer ne gym join kiya, lekin pehle poocha: “Yahan push-ups hain ya sirf push notifications?”',
    'Programmer ki billi keyboard par kyun baithi thi? Woh bhi apni life mein kuch input dena chahti thi!',
    'Programmer ne kaha: “Main multitasking karta hoon.” Dost bola: “Kaise?” Programmer: “Ek saath code bhi nahi chalta aur chai bhi thandi hoti rehti hai!”',
    'Ek bug ne doosre bug se kaha: “Chalo code mein chhup jaate hain.” Doosra bola: “Nahi, programmer ne debugger khol liya hai!”',
    'Programmer ka favourite mausam? Cloudy! Kyunke uska saara kaam cloud mein hota hai!',
    'Programmer ne password rakha “incorrect”. Ab password bhoolta hai to computer khud bata deta hai: “Your password is incorrect!”',
    'Programmer ki car start kyun nahi hui? Usne ignition ko restart karne ke bajaye update kar diya!',
    'Programmer restaurant gaya aur waiter se bola: “Menu ka source code dikhao, mujhe ingredients debug karne hain!”',
    'Programmer ka sab se bara darr kya hai? Boss ka message: “Bas chhota sa change hai.”',
    'Programmer ne dost ko kaha: “Mera code bilkul perfect hai.” Dost bola: “Phir computer ro kyun raha hai?”',
    'Programmer ki date kaisi guzri? Pehle connection bana, phir timeout ho gaya!',
    'Programmer ne mirror mein dekha aur bola: “Aaj to main handsome lag raha hoon.” Mirror bola: “Cache purani hai, refresh karo!”',
    'Programmer ne kaha: “Mujhe thora space chahiye.” Computer ne 500 GB khaali kar di!',
    'Programmer se poocha: “Tum itne khamosh kyun ho?” Bola: “Main abhi apne thoughts compile kar raha hoon!”',
]

def set_status(message):
    if status_ref:
        status_ref.value = message
        try:
            page_ref.update()
        except Exception:
            pass

def add_log(who, message):
    if conversation_ref:
        conversation_ref.controls.append(
            ft.Text(f"{who}: {message}", selectable=True)
        )
        # Keep the latest messages only
        if len(conversation_ref.controls) > 80:
            conversation_ref.controls = conversation_ref.controls[-80:]
        try:
            page_ref.update()
        except Exception:
            pass

async def _speak_async(text):
    """Generate an English MP3 voice reply and play it using Windows' built-in audio API.

    This avoids pygame, which may not have a compatible wheel for Python 3.14.
    """
    path = os.path.join(tempfile.gettempdir(), "jarvis_reply.mp3")
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(path)

    if os.name != "nt":
        raise RuntimeError("Built-in JARVIS audio playback currently requires Windows.")

    winmm = ctypes.WinDLL("winmm")
    send = winmm.mciSendStringW
    send.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
    send.restype = ctypes.c_uint
    alias = "jarvisAudio"
    # Close a leftover alias after a previous playback error, if one exists.
    send(f"close {alias}", None, 0, None)
    # MCI accepts a quoted path; escape embedded quotes defensively.
    safe_path = path.replace('"', '')
    error = send(f'open "{safe_path}" type mpegvideo alias {alias}', None, 0, None)
    if error:
        raise RuntimeError(f"Windows could not open the generated MP3 (MCI error {error}).")
    try:
        error = send(f"play {alias}", None, 0, None)
        if error:
            raise RuntimeError(f"Windows could not play the generated MP3 (MCI error {error}).")
        mode_buffer = ctypes.create_unicode_buffer(128)
        while True:
            await asyncio.sleep(0.12)
            mode_buffer.value = ""
            send(f"status {alias} mode", mode_buffer, len(mode_buffer), None)
            if mode_buffer.value.lower() != "playing":
                break
    finally:
        send(f"close {alias}", None, 0, None)

def speak(text):
    if not text:
        return
    add_log("JARVIS", text)
    try:
        asyncio.run(_speak_async(text))
    except Exception as exc:
        print("Voice playback error:", exc)
        set_status("Voice playback error. Check the terminal for details.")

def clean_command(text):
    text = text.lower().strip()
    text = re.sub(r"\bjarvis\b", "", text)
    text = re.sub(r"^[\s,.:;!?-]+|[\s,.:;!?-]+$", "", text)
    text = re.sub(r"^(please\s+)", "", text)
    return text.strip()

def get_time_date_reply(command):
    c = clean_command(command)
    time_requested = any(x in c for x in [
        "time", "clock", "what time", "current time"
    ])
    date_requested = any(x in c for x in [
        "date", "today's date", "todays date", "day is it", "what day"
    ])
    if not time_requested and not date_requested:
        return None

    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Karachi"))
    except Exception:
        now = datetime.now()

    parts = []
    if time_requested:
        parts.append("The current time in Pakistan is " + now.strftime("%I:%M %p").lstrip("0") + ".")
    if date_requested:
        parts.append("Today's date in Pakistan is " + now.strftime("%A, %B %d, %Y") + ".")
    return " ".join(parts)

def open_website_or_search(command):
    """Handle direct website commands and general Google/YouTube searches."""
    c = clean_command(command)
    c = re.sub(r"^(can you|could you|would you|will you)\s+", "", c)
    c = re.sub(r"^(please\s+)?(open|go to|launch|visit)\s+", "", c)

    # Explicit websites
    sites = {
        "google": "https://www.google.com",
        "youtube": "https://www.youtube.com",
        "instagram": "https://www.instagram.com",
        "facebook": "https://www.facebook.com",
        "tiktok": "https://www.tiktok.com",
        "gmail": "https://mail.google.com",
        "google maps": "https://maps.google.com",
        "maps": "https://maps.google.com",
        "chatgpt": "https://chatgpt.com",
        "whatsapp": "https://web.whatsapp.com",
        "github": "https://github.com",
        "stackoverflow": "https://stackoverflow.com",
        "wikipedia": "https://www.wikipedia.org",
        "netflix": "https://www.netflix.com",
        "amazon": "https://www.amazon.com",
        "bing": "https://www.bing.com",
    }
    normalized = c.rstrip(" .!?")
    if normalized in sites:
        webbrowser.open(sites[normalized])
        return f"Opening {normalized}."

    # Natural-language search patterns:
    # "open Google and search for Python courses"
    # "search for Python courses"
    # "search Google for Python courses"
    # "find me Python courses"
    # "look up Python courses"
    # "search YouTube for Python tutorials"
    search_text = c
    engine = "google"

    yt_match = re.search(r"\b(?:search|find|look up)\s+(?:on\s+)?youtube\s+(?:for\s+)?(.+)", search_text)
    if yt_match:
        engine = "youtube"
        search_text = yt_match.group(1).strip()
    else:
        # "search YouTube for ..."
        yt_match2 = re.search(r"\b(?:search|find)\s+(.+?)\s+on\s+youtube\b", search_text)
        if yt_match2:
            engine = "youtube"
            search_text = yt_match2.group(1).strip()
        else:
            # "open YouTube and search for ..."
            yt_match3 = re.search(r"\b(?:open|go to)\s+youtube\s+and\s+search\s+(?:for\s+)?(.+)", search_text)
            if yt_match3:
                engine = "youtube"
                search_text = yt_match3.group(1).strip()
            else:
                # Remove search lead-ins and optional "Google"
                patterns = [
                    r"^(?:open\s+)?google\s+and\s+search\s+(?:for\s+)?",
                    r"^(?:search\s+)?google\s+for\s+",
                    r"^(?:search|find)\s+(?:for\s+)?",
                    r"^look\s+up\s+",
                    r"^find\s+me\s+",
                    r"^tell\s+me\s+about\s+",
                    r"^what\s+is\s+",
                    r"^who\s+is\s+",
                    r"^how\s+to\s+",
                ]
                for pattern in patterns:
                    if re.search(pattern, search_text):
                        search_text = re.sub(pattern, "", search_text, count=1).strip()
                        break
                # If the user explicitly asks to open Google and search, use Google.
                if re.match(r"^(?:open\s+)?google\s+and\s+search\b", c):
                    search_text = re.sub(r"^(?:open\s+)?google\s+and\s+search\s+(?:for\s+)?", "", c).strip()

    search_text = search_text.strip(" .!?")
    # Avoid treating simple commands as searches.
    if search_text and (
        re.match(r"^(search|find|look up)\b", c)
        or re.match(r"^(?:open\s+)?google\s+and\s+search\b", c)
        or re.match(r"^(?:search|find)\b.*\byoutube\b", c)
        or re.match(r"^look\s+up\b", c)
        or re.match(r"^find\s+me\b", c)
        or re.match(r"^(?:what is|who is|how to)\b", c)
        or re.match(r"^tell me about\b", c)
        or re.match(r"^open youtube and search\b", c)
    ):
        if engine == "youtube":
            url = "https://www.youtube.com/results?search_query=" + quote_plus(search_text)
        else:
            url = "https://www.google.com/search?q=" + quote_plus(search_text)
        webbrowser.open(url)
        return f"Searching {engine.title()} for {search_text}. I have opened the results in your browser."

    return None

def try_open_windows_app(command):
    """Try to launch an installed Windows app from the Start menu app list."""
    c = clean_command(command)
    m = re.match(r"^(?:open|launch|start)\s+(.+)$", c)
    if not m:
        return None
    app_name = m.group(1).strip()
    if app_name in {
        "google", "youtube", "instagram", "facebook", "tiktok", "gmail",
        "google maps", "maps", "chatgpt", "whatsapp", "github", "stackoverflow",
        "wikipedia", "netflix", "amazon", "bing"
    }:
        return None

    # Try direct Windows URI / app launch first for common apps.
    known_commands = {
        "calculator": ["calc.exe"],
        "notepad": ["notepad.exe"],
        "paint": ["mspaint.exe"],
        "command prompt": ["cmd.exe"],
        "cmd": ["cmd.exe"],
        "file explorer": ["explorer.exe"],
        "explorer": ["explorer.exe"],
        "settings": ["cmd", "/c", "start", "ms-settings:"],
    }
    if app_name in known_commands:
        try:
            subprocess.Popen(known_commands[app_name], shell=False)
            return f"Opening {app_name}."
        except Exception:
            pass

    # Find matching installed Start-menu app by display name.
    try:
        ps_script = (
            "$apps = Get-StartApps; "
            "$match = $apps | Where-Object { $_.Name -like '*" +
            app_name.replace("'", "''") +
            "*' } | Select-Object -First 1; "
            "if ($match) { Start-Process ('shell:AppsFolder\\' + $match.AppID); exit 0 } "
            "else { exit 2 }"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True, text=True, timeout=8
        )
        if result.returncode == 0:
            return f"Trying to open {app_name}."
    except Exception:
        pass
    return f"I couldn't find an installed app named {app_name}. I can search for it on Google if you say, 'search Google for {app_name}'."

def handle_special_command(raw_command):
    c = clean_command(raw_command)

    # Time/date must be handled locally, not by the AI model.
    reply = get_time_date_reply(c)
    if reply:
        return reply

    if any(x in c for x in ["tell me a joke", "tell me jokes", "make me laugh", "say a joke", "some jokes", "joke please", "jokes", "joke sunao", "mazaq sunao", "latifa sunao", "koi joke", "koi mazaq", "programming joke"]):
        return random.choice(JOKES)

    if any(x in c for x in ["stop listening", "go to sleep", "sleep mode", "stop jarvis"]):
        global is_listening
        is_listening = False
        return "Okay. I am going to sleep. Say Jarvis again after you start listening."

    # Direct websites and browser searches.
    reply = open_website_or_search(c)
    if reply:
        return reply

    # Try launching an installed Windows app.
    reply = try_open_windows_app(c)
    if reply:
        return reply

    return None

def ask_gemini(command):
    """Ask Gemini for a general conversation reply using the API key in the environment."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return (
            "Gemini API key is not set. In the same PowerShell window, set "
            "the GEMINI_API_KEY environment variable, then restart JARVIS."
        )

    system_instruction = (
        "You are JARVIS, a helpful, polite, futuristic English-speaking desktop assistant. "
        "Always answer in clear, natural English and keep replies concise unless more detail is requested. "
        "If asked for a joke, tell a clean joke. Never claim you opened an app or searched the web "
        "unless the program has actually done so. The application handles local time/date questions. "
        "For current facts, be honest about limitations and suggest a web search if needed."
    )

    try:
        response = requests.post(
            GEMINI_API_URL,
            headers={
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
            },
            json={
                "systemInstruction": {"parts": [{"text": system_instruction}]},
                "contents": [{"role": "user", "parts": [{"text": command}]}],
                "generationConfig": {"temperature": 0.5, "maxOutputTokens": 180},
            },
            timeout=20,
        )

        if response.status_code == 400:
            print("Gemini API returned 400:", response.text[:500])
            return "Gemini could not understand the request. Please try asking in a different way."
        if response.status_code in (401, 403):
            print("Gemini API authentication/permission error:", response.status_code, response.text[:500])
            return "Gemini rejected the API key or the key does not have access. Check your key in Google AI Studio."
        if response.status_code == 404:
            print("Gemini model not found:", response.text[:500])
            return "The selected Gemini model was not found. Check the GEMINI_MODEL setting."
        if response.status_code == 429:
            return "Gemini is busy or the API quota has been reached. Please wait a little and try again."

        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            print("Gemini returned no candidates:", str(data)[:500])
            return "Gemini did not return an answer. Please try again."

        parts = candidates[0].get("content", {}).get("parts", [])
        answer = " ".join(part.get("text", "") for part in parts if part.get("text"))
        return answer.strip() or "Sorry, Gemini returned an empty answer. Please try again."

    except requests.exceptions.ConnectionError:
        return "I cannot reach Gemini. Please check your internet connection."
    except requests.exceptions.Timeout:
        return "Gemini took too long to respond. Please try again."
    except requests.exceptions.HTTPError as exc:
        print("Gemini HTTP error:", exc)
        return "Gemini returned an error. Please check the terminal for details."
    except (ValueError, KeyError, TypeError) as exc:
        print("Gemini response parsing error:", exc)
        return "I received an unexpected response from Gemini. Please try again."
    except Exception as exc:
        print("Gemini error:", exc)
        return "Sorry, something went wrong while I was preparing the answer."

def process_command(raw_command):
    command = clean_command(raw_command)
    if not command:
        speak("I didn't catch that. Please say your command again.")
        return

    add_log("You", raw_command)
    set_status("Thinking...")
    reply = handle_special_command(command)
    if reply is None:
        reply = ask_gemini(command)
    speak(reply)
    set_status("Listening for Jarvis..." if is_listening else "Stopped")

def listen_for_command(source):
    """After hearing the wake word, listen for one complete request."""
    set_status("Yes? I'm listening...")
    speak("Yes?")
    try:
        audio = recognizer.listen(source, timeout=6, phrase_time_limit=12)
        command = recognizer.recognize_google(audio, language=SPEECH_LANGUAGE)
        process_command(command)
    except sr.WaitTimeoutError:
        speak("I didn't hear a question. Say Jarvis when you're ready.")
    except sr.UnknownValueError:
        speak("Sorry, I didn't understand that. Please try again.")
    except sr.RequestError:
        speak("Speech recognition is unavailable. Please check your internet connection.")
    except Exception as exc:
        print("Listening error:", exc)
        set_status("Microphone error. Check your microphone settings.")

def listen_loop():
    global is_listening
    try:
        with sr.Microphone(device_index=MIC_DEVICE) as source:
            set_status("Calibrating microphone...")
            recognizer.adjust_for_ambient_noise(source, duration=0.8)
            speak("JARVIS online. Say Jarvis, then ask your question.")
            set_status("Listening for 'Jarvis'...")
            while is_listening:
                try:
                    audio = recognizer.listen(source, timeout=2, phrase_time_limit=6)
                    heard = recognizer.recognize_google(audio, language=SPEECH_LANGUAGE)
                    print("Heard:", heard)
                    if "jarvis" in heard.lower():
                        # Support both "Jarvis" alone and "Jarvis, what time is it?"
                        after_wake = re.sub(r".*?\bjarvis\b", "", heard, count=1, flags=re.IGNORECASE).strip(" ,.!?")
                        if after_wake:
                            process_command(after_wake)
                        else:
                            listen_for_command(source)
                        if is_listening:
                            set_status("Listening for 'Jarvis'...")
                except sr.WaitTimeoutError:
                    continue
                except sr.UnknownValueError:
                    continue
                except sr.RequestError:
                    set_status("Speech recognition needs internet. Retrying...")
                    threading.Event().wait(2)
                except Exception as exc:
                    print("Microphone loop error:", exc)
                    set_status("Microphone error. Check your microphone settings.")
                    threading.Event().wait(2)
    except Exception as exc:
        print("Could not start microphone:", exc)
        set_status("Could not open microphone. Check microphone permissions/device.")
        is_listening = False
    set_status("Stopped")

def talk_now_thread():
    """Listen to one question immediately; no wake word is required."""
    set_status("Opening microphone...")
    try:
        with sr.Microphone(device_index=MIC_DEVICE) as source:
            set_status("Listening now — speak clearly...")
            recognizer.adjust_for_ambient_noise(source, duration=0.35)
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
        set_status("Recognizing speech...")
        command = recognizer.recognize_google(audio, language=SPEECH_LANGUAGE)
        print("Heard:", command)
        process_command(command)
    except sr.WaitTimeoutError:
        set_status("I did not hear anything. Click Talk Now and try again.")
    except sr.UnknownValueError:
        set_status("I could not understand that. Please try again.")
    except sr.RequestError as exc:
        print("Speech recognition request error:", exc)
        set_status("Speech recognition needs internet. Check connection.")
    except Exception as exc:
        print("Talk Now microphone error:", exc)
        set_status("Microphone unavailable. Check Windows microphone permission.")

def talk_now(e=None):
    threading.Thread(target=talk_now_thread, daemon=True).start()

def start_listening(e=None):
    global is_listening, listener_thread
    if is_listening:
        return
    is_listening = True
    listener_thread = threading.Thread(target=listen_loop, daemon=True)
    listener_thread.start()
    if page_ref:
        page_ref.update()

def stop_listening(e=None):
    global is_listening
    is_listening = False
    set_status("Stopping...")

def main(page: ft.Page):
    global page_ref, status_ref, conversation_ref
    page_ref = page
    page.title = "JARVIS | AI Assistant — FINAL"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#030914"
    page.window.width = 1180
    page.window.height = 780
    page.window.min_width = 850
    page.window.min_height = 620
    page.padding = 0

    # JARVIS visual theme
    BLUE = "#19BFFF"
    PALE = "#EAF7FF"
    MUTED = "#88AFCB"
    PANEL = "#071729"
    EDGE = "#123A5C"
    GREEN = "#24E3A5"

    status_ref = ft.Text(
        "Ready when you are",
        size=12,
        color=BLUE,
        weight=ft.FontWeight.W_500,
    )
    conversation_ref = ft.Column(
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    def panel_card(content, padding=16, bgcolor=PANEL):
        return ft.Container(
            content=content,
            padding=padding,
            bgcolor=bgcolor,
            border=ft.Border.all(1, EDGE),
            border_radius=18,
        )

    logo = ft.Container(
        content=ft.Text("J", size=38, weight=ft.FontWeight.BOLD, color=PALE),
        width=66,
        height=66,
        alignment=ft.Alignment(0, 0),
        bgcolor="#062747",
        border=ft.Border.all(2, BLUE),
        border_radius=33,
        shadow=ft.BoxShadow(blur_radius=24, spread_radius=1, color="#164C99"),
    )

    def make_button_style(bgcolor, border_color=BLUE):
        return ft.ButtonStyle(
            bgcolor=bgcolor,
            color=PALE,
            side=ft.BorderSide(1, border_color),
            shape=ft.RoundedRectangleBorder(radius=22),
            padding=ft.Padding(18, 12, 18, 12),
        )

    start_button = ft.Button(
        content="Start Listening",
        icon=ft.Icons.MIC,
        on_click=start_listening,
        style=make_button_style("#07518A"),
    )
    talk_button = ft.Button(
        content="Talk Now",
        icon=ft.Icons.MIC,
        on_click=talk_now,
        style=make_button_style("#087F8C", "#35E6E6"),
    )

    stop_button = ft.OutlinedButton(
        "Stop Listening",
        icon=ft.Icons.STOP,
        on_click=stop_listening,
        style=ft.ButtonStyle(
            color=PALE,
            side=ft.BorderSide(1, EDGE),
            shape=ft.RoundedRectangleBorder(radius=22),
            padding=ft.Padding(16, 12, 16, 12),
        ),
    )

    manual_input = ft.TextField(
        hint_text="Message JARVIS…",
        expand=True,
        border_color=EDGE,
        focused_border_color=BLUE,
        bgcolor="#04111F",
        color=PALE,
        border_radius=18,
        text_size=14,
        content_padding=ft.Padding(16, 14, 16, 14),
        on_submit=lambda e: submit_text(e.control.value),
    )

    def submit_text(value):
        if value and value.strip():
            manual_input.value = ""
            page.update()
            threading.Thread(
                target=process_command, args=(value,), daemon=True
            ).start()

    send_button = ft.Button(
        content="Send",
        icon=ft.Icons.SEND,
        on_click=lambda e: submit_text(manual_input.value),
        style=make_button_style("#073B65"),
    )

    # Clean top bar: remove redundant navigation labels and technical footer text.
    header = ft.Container(
        padding=ft.Padding(26, 18, 26, 18),
        bgcolor="#040D18",
        border=ft.Border.only(bottom=ft.BorderSide(1, EDGE)),
        content=ft.Row(
            [
                ft.Row(
                    [
                        ft.Container(
                            content=ft.Text("J", size=25, weight=ft.FontWeight.BOLD, color=BLUE),
                            width=44,
                            height=44,
                            alignment=ft.Alignment(0, 0),
                            border=ft.Border.all(1, BLUE),
                            border_radius=22,
                            bgcolor="#062747",
                        ),
                        ft.Column(
                            [
                                ft.Text("JARVIS", size=21, color=PALE, weight=ft.FontWeight.BOLD),
                                ft.Text("Your personal AI assistant", size=12, color=MUTED),
                            ],
                            spacing=2,
                        ),
                    ],
                    spacing=12,
                ),
                ft.Container(expand=True),
                ft.Row(
                    [
                        ft.Container(width=8, height=8, bgcolor=GREEN, border_radius=4),
                        ft.Text("STANDBY", size=12, color=GREEN, weight=ft.FontWeight.BOLD),
                    ],
                    spacing=8,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )

    welcome_card = panel_card(
        ft.Row(
            [
                ft.Container(
                    content=ft.Icon(ft.Icons.AUTO_AWESOME, color=BLUE, size=30),
                    width=58,
                    height=58,
                    alignment=ft.Alignment(0, 0),
                    bgcolor="#082A48",
                    border=ft.Border.all(1, EDGE),
                    border_radius=16,
                ),
                ft.Column(
                    [
                        ft.Text("How can I help you?", size=20, color=PALE, weight=ft.FontWeight.BOLD),
                        ft.Text(
                            "Click Talk Now to speak once, or Start Listening to use the Jarvis wake word.",
                            size=13,
                            color=MUTED,
                        ),
                    ],
                    spacing=5,
                    expand=True,
                ),
            ],
            spacing=15,
        ),
        padding=18,
    )

    voice_card = panel_card(
        ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.GRAPHIC_EQ, color=BLUE, size=22),
                        ft.Text("Voice control", color=PALE, size=15, weight=ft.FontWeight.BOLD),
                        ft.Container(expand=True),
                        status_ref,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row([talk_button, start_button, stop_button], spacing=10, wrap=True),
            ],
            spacing=13,
        ),
        padding=16,
    )

    chat_card = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.FORUM_OUTLINED, color=BLUE, size=21),
                        ft.Text("Conversation", size=15, color=PALE, weight=ft.FontWeight.BOLD),
                        ft.Container(expand=True),
                        ft.Icon(ft.Icons.CHEVRON_RIGHT, color=MUTED, size=18),
                    ]
                ),
                ft.Divider(color=EDGE),
                ft.Container(content=conversation_ref, expand=True, padding=8),
            ],
            spacing=8,
            expand=True,
        ),
        expand=True,
        padding=16,
        bgcolor="#040F1C",
        border=ft.Border.all(1, EDGE),
        border_radius=18,
    )

    composer = ft.Row([manual_input, send_button], spacing=10)

    page.add(
        ft.Column(
            [
                header,
                ft.Container(
                    content=ft.Column(
                        [welcome_card, voice_card, chat_card, composer],
                        spacing=14,
                        expand=True,
                    ),
                    padding=22,
                    expand=True,
                ),
            ],
            spacing=0,
            expand=True,
        )
    )

if __name__ == "__main__":
    # Compatible with many Flet versions
    ft.run(main)

from concurrent.futures import ThreadPoolExecutor
import speech_recognition as sr
from asyncio import create_task
from board import SCL, SDA
import adafruit_ssd1306
import traceback
import subprocess
import textwrap
import logging
import asyncio
import pyttsx3
import busio
import openai
import time
import os

logging.basicConfig(filename='events.log', level=logging.DEBUG)

# Initialize the speech recognition engine
r = sr.Recognizer()
openai.api_key = os.environ['OPENAI_API_KEY']
executor = ThreadPoolExecutor()

# Initialize the text-to-speech engine
engine = pyttsx3.init()
# Set properties
engine.setProperty('rate', 150)
engine.setProperty('volume', 1.0)
# Direct audio to specific hardware
engine.setProperty('alsa_device', 'hw:Headphones,0')
speak_lock = asyncio.Lock()

def initLCD():
    # Create the I2C interface.
    i2c = busio.I2C(SCL, SDA)

    # Create the SSD1306 OLED class.
    # The first two parameters are the pixel width and pixel height. Change these
    # to the right size for your display
    display = adafruit_ssd1306.SSD1306_I2C(128, 32, i2c)
    # Alternatively, you can change the I2C address of the device with an addr parameter:
    # display = adafruit_ssd1306.SSD1306_I2C(128, 32, i2c, addr=0x31)

    # Set the display rotation to 180 degrees.
    display.rotation = 2

    # Clear the display. Always call show after changing pixels to make the display
    # update visible
    display.fill(0)

    # Display IP address
    ip_address = subprocess.check_output(["hostname", "-I"]).decode("utf-8").split(" ")[0]
    display.text(f"IP: {ip_address}", 0, 0, 1)

    # Show the updated display with the text.
    display.show()
    return display

async def updateLCD(text, display, error=False):
    stop_event = asyncio.Event()

    async def display_lines(start, end):
        display.fill_rect(0, 10, 128, 22, 0)
        for i, line_index in enumerate(range(start, end)):
            display.text(lines[line_index], 0, 10 + i * 10, 1)
        display.show()

    async def loop_text():
        i = 0
        while not stop_event.is_set():
            await display_lines(i, i + 2)
            await asyncio.sleep(2)
            i = (i + 1) % (line_count - 1)

    display.fill(0)
    ip_address = subprocess.check_output(["hostname", "-I"]).decode("utf-8").split(" ")[0]
    display.text(f"IP: {ip_address}", 0, 0, 1)
    display.show()

    lines = textwrap.fill(text, 21).split('\n')
    line_count = len(lines)

    loop_task = asyncio.create_task(loop_text())
    speaking_task = asyncio.create_task(speak(text))

    tasks = [loop_task, speaking_task]
    if not error:
        query_task = asyncio.create_task(query_openai(text))
        tasks.append(query_task)

    await asyncio.gather(*tasks)
    loop_task.cancel()

    stop_event.set()

async def listen_speech(loop, display, state_task):
    def recognize_audio():
        with sr.Microphone() as source:
            audio = r.listen(source)
            return r.recognize_google(audio)
    text = await loop.run_in_executor(executor, recognize_audio)
    state_task.cancel()
    return text

async def display_state(state, display):
    while True:
        for i in range(4):
            display.fill_rect(0, 10, 128, 22, 0)
            display.text(f"{state}" + '.' * i, 0, 20, 1)
            display.show()
            await asyncio.sleep(0.5)

async def speak(text):
    async with speak_lock:
        loop = asyncio.get_running_loop()
        def _speak():
            engine.say(text)
            engine.runAndWait()
        await loop.run_in_executor(executor, _speak)

async def query_openai(text):
    try:
        response = openai.Completion.create(
            engine="davinci",
            prompt=f"Q: {text}\nA: (But add a hint of snark and sarcasm)",
            temperature=0.9,
            max_tokens=64,
            top_p=1,
            frequency_penalty=0.0,
            presence_penalty=0.6,
            stop=["\n"]
        )
        message = f"Response: {response.choices[0].text}"
        await speak(message)
        log_event(message)
    except Exception as e:
        await speak(f"Something went wrong: {e}")
        log_event(f"Error: {traceback.format_exc()}")

def log_event(text):
    logging.info(text)
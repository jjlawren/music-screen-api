"""
This file is for use with the Pimoroni HyperPixel 4.0 Square (Non Touch) High Res display
it integrates with your local Sonos sytem to display what is currently playing
"""

import asyncio
import logging
import os
import signal
import sys
import time
import tkinter as tk
from io import BytesIO
from tkinter import font as tkFont

from aiohttp import ClientError, ClientSession
from PIL import Image, ImageFile, ImageTk

import demaster
from hyperpixel_backlight import Backlight
import scrap
from sonos_user_data import SonosData
from webhook_handler import SonosWebhook

_LOGGER = logging.getLogger(__name__)

try:
    import sonos_settings
except ImportError:
    _LOGGER.error("ERROR: Config file not found. Copy 'sonos_settings.py.example' to 'sonos_settings.py' and edit.")
    sys.exit(1)


class TkData():

    def __init__(self, root, album_frame, curtain_frame, detail_text, label_albumart, track_name):
        """Initialize the object."""
        self.root = root
        self.album_frame = album_frame
        self.album_image = None
        self.curtain_frame = curtain_frame
        self.detail_text = detail_text
        self.label_albumart = label_albumart
        self.track_name = track_name
        self.is_showing = False

    def show_album(self, should_show):
        """Control if album art should be displayed or hidden."""
        if should_show != self.is_showing:
            if should_show:
                self.album_frame.lift()
            else:
                self.curtain_frame.lift()
            self.is_showing = should_show
        self.root.update()


## Remote debug mode - only activate if you are experiencing issues and want the developer to help
remote_debug_key = ""
if remote_debug_key != "":
    print ("Remote debugging being set up - waiting 10 seconds for wifi to get working")
    time.sleep(10)
    scrap.setup (remote_debug_key)
    scrap.auto_scrap_on_print()
    scrap.auto_scrap_on_error()
    scrap.new_section()
    scrap.write ("App start")

###############################################################################
# Parameters and global variables

# set user variables
thumbsize = 600,600   # pixel size of thumbnail if you're displaying detail
screensize = 720,720  # pixel size of HyperPixel 4.0
fullscreen = True
thumbwidth = thumbsize[1]
screenwidth = screensize[1]

POLLING_INTERVAL = 1
WEBHOOK_INTERVAL = 60

ImageFile.LOAD_TRUNCATED_IMAGES = True

###############################################################################
# Functions

async def get_image_data(session, url):
    """Return image data from a URL if available."""
    if not url:
        return None

    try:
        async with session.get(url) as response:
            content_type = response.headers.get('content-type')
            if content_type and not content_type.startswith('image/'):
                _LOGGER.warning("Not a valid image type (%s): %s", content_type, url)
                return None
            return await response.read()
    except ClientError as err:
        _LOGGER.warning("Problem connecting to %s [%s]", url, err)
    except Exception as err:
        _LOGGER.warning("Image failed to load: %s [%s]", url, err)
    return None

async def redraw(session, sonos_data, tk_data, backlight):
    """Redraw the screen with current data."""
    if sonos_data.status == "API error":
        if remote_debug_key != "": print ("API error reported fyi")
        return

    current_artist = sonos_data.artist
    current_album = sonos_data.album
    current_duration = sonos_data.duration
    current_image_url = sonos_data.image
    current_trackname = sonos_data.trackname
    pil_image = None

    # see if something is playing
    if sonos_data.status == "PLAYING":
        if remote_debug_key != "": print ("Music playing")

        if not sonos_data.is_track_new():
            # Ensure the album frame is displayed in case the current track was paused, seeked, etc
            tk_data.show_album(True)
            backlight.set_power(True)
            return

        # slim down the trackname
        if sonos_settings.demaster:
            offline = not getattr(sonos_settings, "demaster_query_cloud", False)
            current_trackname = demaster.strip_name(current_trackname, offline)
            if remote_debug_key != "": print ("Demastered to " + current_trackname)
            _LOGGER.debug("Demastered to %s", current_trackname)

        image_data = await get_image_data(session, current_image_url)
        if image_data:
            pil_image = Image.open(BytesIO(image_data))

        if pil_image is None:
            pil_image = Image.open(sys.path[0] + "/sonos.png")
            _LOGGER.warning("Image not available, using default")

        # set the image size and text based on whether we are showing track details as well
        if sonos_settings.show_details == True:
            target_image_width = thumbwidth
            tk_data.track_name.set(current_trackname)
            detail_text = f"{current_artist} • {current_album}"
            tk_data.detail_text.set(detail_text)
        else:
            target_image_width = screenwidth

        # resize the image
        wpercent = (target_image_width/float(pil_image.size[0]))
        hsize = int((float(pil_image.size[1])*float(wpercent)))
        pil_image = pil_image.resize((target_image_width,hsize), Image.ANTIALIAS)

        # Store the image as an attribute to preserve scope for Tk
        tk_data.album_image = ImageTk.PhotoImage(pil_image)
        tk_data.label_albumart.configure(image=tk_data.album_image)
        tk_data.show_album(True)
        backlight.set_power(True)
    else:
        backlight.set_power(False)
        tk_data.show_album(False)
        if remote_debug_key != "": print ("Track not playing - doing nothing")


# Create the main window
root = tk.Tk()
root.geometry("720x720")
root.title("Music Display")

album_frame = tk.Frame(root, bg='black', width=720, height=720)
curtain_frame = tk.Frame(root, bg='black', width=720, height=720)

album_frame.grid(row=0, column=0, sticky="news")
curtain_frame.grid(row=0, column=0, sticky="news")

# Set variables
track_name = tk.StringVar()
detail_text = tk.StringVar()
if sonos_settings.show_artist_and_album:
    track_font = tkFont.Font(family='Helvetica', size=30)
else:
    track_font = tkFont.Font(family='Helvetica', size=40)
image_font = tkFont.Font(size=25)
detail_font = tkFont.Font(family='Helvetica', size=15)

# Create widgets
label_albumart = tk.Label(album_frame,
                        image=None,
                        font=image_font,
                        borderwidth=0,
                        highlightthickness=0,
                        fg='white',
                        bg='black')
label_track = tk.Label(album_frame,
                        textvariable=track_name,
                        font=track_font,
                        fg='white',
                        bg='black',
                        wraplength=600,
                        justify="center")
label_detail = tk.Label(album_frame,
                        textvariable=detail_text,
                        font=detail_font,
                        fg='white',
                        bg='black',
                        wraplength=600,
                        justify="center")


if sonos_settings.show_details == False:
    label_albumart.place (relx=0.5, rely=0.5, anchor=tk.CENTER)

if sonos_settings.show_details == True:
    label_albumart.place(x=360, y=thumbsize[1]/2, anchor=tk.CENTER)
    label_track.place (x=360, y=thumbsize[1]+20, anchor=tk.N)

    label_track.update()
    height_of_track_label = label_track.winfo_reqheight()

    if sonos_settings.show_artist_and_album:
        label_detail.place (x=360, y=710, anchor=tk.S)

album_frame.grid_propagate(False)

# Start in fullscreen mode
root.attributes('-fullscreen', fullscreen)
root.update()

tk_data = TkData(root, album_frame, curtain_frame, detail_text, label_albumart, track_name)

def setup_logging():
    """Set up logging facilities for the script."""
    log_level = getattr(sonos_settings, "log_level", logging.DEBUG)
    log_file = getattr(sonos_settings, "log_file", None)
    if log_file:
        log_path = os.path.expanduser(log_file)
    else:
        log_path = None

    fmt = "%(asctime)s %(levelname)7s - %(message)s"
    logging.basicConfig(format=fmt, level=log_level)

    # Suppress overly verbose logs from libraries that aren't helpful
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("PIL.PngImagePlugin").setLevel(logging.WARNING)

    if log_path is None:
        return

    log_path_exists = os.path.isfile(log_path)
    log_dir = os.path.dirname(log_path)

    if (log_path_exists and os.access(log_path, os.W_OK)) or (
        not log_path_exists and os.access(log_dir, os.W_OK)
    ):
        _LOGGER.info("Writing to log file: %s", log_path)
        logfile_handler = logging.FileHandler(log_path, mode="a")

        logfile_handler.setLevel(log_level)
        logfile_handler.setFormatter(logging.Formatter(fmt))

        logger = logging.getLogger("")
        logger.addHandler(logfile_handler)
    else:
        _LOGGER.error("Cannot write to %s, check permissions and ensure directory exists", log_path)

async def main(loop):
    """Main process for script."""
    setup_logging()

    backlight = Backlight()

    if sonos_settings.room_name_for_highres == "":
        print ("No room name found in sonos_settings.py")
        print ("You can specify a room name manually below")
        print ("Note: manual entry works for testing purposes, but if you want this to run automatically on startup then you should specify a room name in sonos_settings.py")
        print ("You can edit the file with the command: nano sonos_settings.py")
        print ("")
        sonos_room = input ("Enter a Sonos room name for testing purposes>>>  ")
    else:
        sonos_room = sonos_settings.room_name_for_highres
        _LOGGER.info("Monitoring room: %s", sonos_room)

    session = ClientSession()
    sonos_data = SonosData(
            sonos_settings.sonos_http_api_address,
            sonos_settings.sonos_http_api_port,
            sonos_room,
            session,
    )

    async def webhook_callback():
        """Callback to trigger after webhook is processed."""
        await redraw(session, sonos_data, tk_data, backlight)

    webhook = SonosWebhook(sonos_data, webhook_callback)
    await webhook.listen()

    for signame in ('SIGINT', 'SIGTERM', 'SIGQUIT'):
        loop.add_signal_handler(getattr(signal, signame), lambda: asyncio.ensure_future(cleanup(loop, session, webhook, backlight)))

    while True:
        if sonos_data.webhook_active:
            update_interval = WEBHOOK_INTERVAL
        else:
            update_interval = POLLING_INTERVAL

        if time.time() - sonos_data.last_update > update_interval:
            await sonos_data.refresh()
            await redraw(session, sonos_data, tk_data, backlight)
        await asyncio.sleep(1)

async def cleanup(loop, session, webhook, backlight):
    """Cleanup tasks on shutdown."""
    _LOGGER.debug("Shutting down")
    backlight.cleanup()
    await session.close()
    await webhook.stop()

    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    [task.cancel() for task in tasks]
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    try:
        loop.create_task(main(loop))
        loop.run_forever()
    finally:
        loop.close()

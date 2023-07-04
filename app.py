#!/usr/bin/env python3

import simplematrixbotlib as botlib
import asyncio
import json
from nio import AsyncClient, MatrixRoom, RoomMessageText
import emoji
from datetime import datetime
import requests
import re
import pprint

import csv
from collections import defaultdict, Counter
from datetime import datetime, timedelta

import opengraph_py3
import snscrape.modules.twitter as sntwitter

from rocketchat_API.rocketchat import RocketChat

CONFIG_FILE = "config.json"
REGISTRATION = {"steps": False}

def read_config(file: str):
    with open(file, "r") as f:
        return json.load(f)

def save_config(file: str):
    with open(file, "w") as f:
        json.dump(config, f)

try:
    config = read_config(CONFIG_FILE)
except:
    print("Error: missing config.json file")
    exit(0)

# TODO: use multiple bots for multiple ingest rooms
ingest_room = config["control"]["ingest_rooms"][0]
creds = botlib.Creds(
    ingest_room["server_url"],
    ingest_room["username"],
    ingest_room["password"]
)
bot = botlib.Bot(creds)
PREFIX = '!'

rocket_config = config["control"]["rocketchat"]
rocket = RocketChat(
    rocket_config["username"],
    rocket_config["password"],
    server_url=rocket_config["server_url"]
)

# TODO: image forward, download image and send it to destination room
# TODO: predict which emoji could be used for a new posted message

def get_specific_tweet(tweet_id):

    # Wait for snsapi to be fixed
    # for i,tweet in enumerate(sntwitter.TwitterTweetScraper(tweetId=tweet_id,mode=sntwitter.TwitterTweetScraperMode.SINGLE).get_items()):
    #     print(tweet)
    #     return json.loads(tweet.json())

    url = "https://cdn.syndication.twimg.com/tweet-result"

    querystring = {"id":tweet_id,"lang":"en"}

    payload = ""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/114.0",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Origin": "https://platform.twitter.com",
        "Connection": "keep-alive",
        "Referer": "https://platform.twitter.com/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
        "TE": "trailers"
    }

    response = requests.request("GET", url, data=payload, headers=headers, params=querystring)

    return response.json()

def save_history(trigger, room, content):

    message_content = content

    with open(config["control"]["log_file"], mode='a') as file_:

        site_name = ""
        title = ""
        description = ""

        try:

            content_url = re.search("(?P<url>https?://[^\s]+)", content).group("url")

            if len(content_url) > 0:

                if content_url.startswith("https://twitter.com"):

                    tweet = get_specific_tweet(content_url.split("/")[-1])
                    pprint.pprint(tweet)
                    pprint.pprint(tweet["text"])
                    site_name = "Twitter"
                    title = tweet["user"]["name"]
                    description = tweet["text"]

                else:

                    og = opengraph_py3.OpenGraph(url=content_url)
                    site_name = og.site_name

                    if og.site_name != "GitHub":
                        title = og.title
                        description = og.description

                if len(description) > 0:
                    message_content = f"{description} / {content.replace('twitter.com', 'nitter.net')} / {emoji.emojize(trigger)}"
                else:
                    message_content = f"{content} / {emoji.emojize(trigger)}"
            else :
                message_content = f"{content} / {emoji.emojize(trigger)}"

        except Exception as er:
            print(f"Error while modifying content: {content}")
            print(er)


        file_.write(
            "{},{},{},{},{},{},{}".format(
                datetime.now(),
                trigger,
                room,
                content,
                site_name,
                title,
                description
            )
        )
        file_.write("\n")

    return message_content

async def send_message(destination_room, content):

    print(f"Sending message to room {destination_room}")

    room = next(
        (x for x in config["rooms"] if x["description"] == destination_room),
        None
    )

    if not room:
        print(f"Error: room {destination_room} not found")
        return

    match room["protocol"]:

        case "matrix":
            await bot.api.send_text_message(
                    room_id=room["room_id"],
                    message=content,
                    msgtype="m.text")

        case "signal":

            signal_config = config["control"]["signal"]

            if signal_config["enabled"]:

                try:
                    x = requests.post(
                        signal_config["url"],
                        json = {
                            "message": content,
                            "number": signal_config["origin_number"],
                            "recipients": [ room["room_id"] ]
                        }
                    )
                except:
                    print("Error: signal server not available")

        case "rocketchat":
            rocket.chat_post_message(
                content,
                channel=room["room_id"]
            )

async def send_help(room):
    help_message = "Available triggers:\n"

    for trigger_item in config["triggers"]:
        triggers = "".join([emoji.emojize(trigger) for trigger in trigger_item["emoji_triggers"]])
        help_message += f"{triggers} - {trigger_item['description']}\n"

    await bot.api.send_text_message(
        room_id=room.room_id,
        message=help_message
    )

async def send_history(room):

    weekday_emojis = defaultdict(Counter)
    one_week_ago = datetime.now() - timedelta(days=7)
    with open(config["control"]["log_file"], "r") as f:
        csv_reader = csv.reader(f)
        next(csv_reader) # skip header row

        for row in csv_reader:
            try:
                timestamp_str, emoji_str = row[0], row[1]
                timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S.%f")
                if timestamp >= one_week_ago:
                    weekday = timestamp.weekday()
                    weekday_emojis[weekday][emoji_str] += 1
            except:
                print("Error on row")


    emoji_counts = []
    for weekday in range(7):
        day = datetime.now() - timedelta(days=weekday)
        day_message = [f"- {day.strftime('%A')}: "]
        counts_for_day = weekday_emojis[weekday]
        # convert to list of tuples and sort by count
        counts_for_day = sorted(counts_for_day.items(), key=lambda x: x[1], reverse=True)
        for emoji_str, count in counts_for_day:
            for index in range(count):
                day_message.append(emoji.emojize(emoji_str))
        emoji_counts.append("".join(day_message))

    history_message = "Latest week emojis:\n" + "\n".join(emoji_counts)

    await bot.api.send_text_message(
        room_id=room.room_id,
        message=history_message
    )

async def register_trigger(room, trigger):
    global REGISTRATION
    REGISTRATION = {
        "steps": 0,
        "emoji_triggers": [trigger],
        "description": "New trigger",
        "destination_rooms": []
    }
    await bot.api.send_text_message(
        room_id=room.room_id,
        message=f"{emoji.emojize(trigger)} - Trigger description?"
    )

@bot.listener.on_message_event
async def on_message(room, message):

    global REGISTRATION
    pprint.pprint(REGISTRATION)

    # TODO: use multiple bots for multiple ingest rooms
    ingest_room = config["control"]["ingest_rooms"][0]
    if room.room_id == ingest_room["room_id"]:

        if REGISTRATION["steps"] != False:

            trigger = REGISTRATION["emoji_triggers"][0]

            match REGISTRATION["steps"]:
                case 0:
                    # Await for trigger name
                    REGISTRATION["description"] = message.content
                    REGISTRATION["steps"] = 1

                    # Setup rooms
                    available_rooms = [room["description"] for room in config["rooms"]]
                    room_setup_message = [
                        f"{emoji.emojize(trigger)} - description: {message.content}",
                        "Select rooms in this list, separate input by ','",
                        ", ".join(available_rooms)
                    ]

                    await bot.api.send_text_message(
                        room_id=room.room_id,
                        message="\n".join(room_setup_message)
                    )
                    pprint.pprint(REGISTRATION)
                    return

                case 1:

                    # Await for room selection
                    selected_rooms = message.content.split(',')

                    for room in config["rooms"]:
                        if room["description"] in selected_rooms:
                            REGISTRATION["destination_rooms"].append(room)

                    # Confirm registration
                    await bot.api.send_text_message(
                        room_id=room.room_id,
                        message="Confirm registration? (y,n)"
                    )

                    REGISTRATION["steps"] = 2
                    return

                case 2:
                    # Registration confirmed? Exit
                    # else go to step 0

                    if message.content == 'y':
                        await bot.api.send_text_message(
                            room_id=room.room_id,
                            message="Registration confirmed"
                        )

                        REGISTRATION.pop("steps")
                        config["triggers"].append(REGISTRATION)

                        try:
                            save_config(CONFIG_FILE)
                        except:
                            print("Error: missing config.json file")
                            exit(0)

                        REGISTRATION = {"steps": False}
                    else:
                        REGISTRATION["steps"] = 0

                    return

        else:

            match = botlib.MessageMatch(room, message, bot, PREFIX)

            if match.is_not_from_this_bot() and match.prefix():

                if match.command("help"):
                    await send_help(room)

                if match.command("history"):
                    await send_history(room)

@bot.listener.on_reaction_event
async def on_reaction(room, event, reaction):

    trigger = emoji.demojize(reaction)
    print(f"User {event.source['sender']} reacted with {trigger}")

    source_event_id = event.source['content']['m.relates_to']['event_id']
    origin_event = await bot.api.async_client.room_get_event(room.room_id, source_event_id)
    content = origin_event.event.body

    # TODO: use multiple bots for multiple ingest rooms
    ingest_room = config["control"]["ingest_rooms"][0]
    if room.room_id == ingest_room["room_id"]:

        trigger_found = False

        for trigger_item in config["triggers"]:

            if trigger in trigger_item["emoji_triggers"]:
                trigger_found = True

                # format message from event content
                message_content = save_history(
                    trigger,
                    destination_room,
                    content
                )

                for destination_room in trigger_item["destination_rooms"]:

                    # send message to destination room
                    await send_message(
                        destination_room,
                        message_content
                    )

        if not trigger_found:
            await register_trigger(room, trigger)

bot.run()

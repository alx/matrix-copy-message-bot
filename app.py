#!/usr/bin/env python3

import simplematrixbotlib as botlib
import asyncio
import json
from nio import AsyncClient, MatrixRoom, RoomMessageText
import emoji
from datetime import datetime
import requests
import re

import csv
from collections import defaultdict, Counter
from datetime import datetime, timedelta

import opengraph_py3
import snscrape.modules.twitter as sntwitter

from rocketchat_API.rocketchat import RocketChat

CONFIG_FILE = "config.json"

def read_config(file: str):
    with open(file, "r") as f:
        return json.load(f)

config = read_config(CONFIG_FILE)

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
    for i,tweet in enumerate(sntwitter.TwitterTweetScraper(tweetId=tweet_id,mode=sntwitter.TwitterTweetScraperMode.SINGLE).get_items()):
        print(tweet)
        return json.loads(tweet.json())

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
                    site_name = "Twitter"
                    title = tweet["user"]["rawDescription"]
                    description = tweet["rawContent"]

                else:

                    og = opengraph_py3.OpenGraph(url=content_url)
                    site_name = og.site_name

                    if og.site_name != "GitHub":
                        title = og.title
                        description = og.description

                message_content = f"{description} / {content.replace('twitter.com', 'nitter.net')} / {emoji.emojize(trigger)}"
            else :
                message_content = f"{content} / {emoji.emojize(trigger)}"

        except:
            print("Error: " + content)


        file_.write(
            "{},{},{},{},{},{},{}".format(
                datetime.now(),
                trigger,
                room["description"],
                content,
                site_name,
                title,
                description
            )
        )
        file_.write("\n")

    return message_content

async def send_message(room, content):

    print(f"Sending message to room {room}")


    match room["protocol"]:

        case "matrix":
            await bot.api.send_text_message(
                    room_id=room["room_id"],
                    message=content,
                    msgtype="m.text")

        case "signal":

            signal_config = config["control"]["signal"]

            if signal_config["enabled"]:
                x = requests.post(
                    signal_config["url"],
                    json = {
                        "message": content,
                        "number": signal_config["origin_number"],
                        "recipients": [ room["room_id"] ]
                    }
                )

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


@bot.listener.on_message_event
async def on_message(room, message):
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

        for trigger_item in config["triggers"]:
            if trigger in trigger_item["emoji_triggers"]:
                for room in trigger_item["destination_rooms"]:

                    # format message from event content
                    message_content = save_history(
                        trigger,
                        room,
                        content
                    )

                    # send message to destination room
                    await send_message(
                        room,
                        message_content
                    )

bot.run()

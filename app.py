#!/usr/bin/env python3

import simplematrixbotlib as botlib
import asyncio
import json
from nio import AsyncClient, MatrixRoom, RoomMessageText
import emoji
from datetime import datetime
import requests

import csv
from collections import defaultdict, Counter
from datetime import datetime, timedelta

CONFIG_FILE = "config.json"

def read_config(file: str):
    with open(file, "r") as f:
        return json.load(f)

config = read_config(CONFIG_FILE)
creds = botlib.Creds(
    config["control"]["server_url"],
    config["control"]["username"],
    config["control"]["password"]
)
bot = botlib.Bot(creds)
PREFIX = '!'

# TODO: /history command taht would parse csv to display used emoji by date during the last week
# TODO: connector to rocketchat network
# TODO: image forward, download image and send it to destination room
# TODO: predict which emoji could be used for a new posted message

def save_history(config, trigger, room, content):

    with open(config["control"]["log_file"], mode='a') as file_:
        file_.write(
            "{},{},{},{}".format(
                datetime.now(),
                trigger,
                room["description"],
                content
            )
        )
        file_.write("\n")

async def send_message(config, trigger, event, trigger_item):

    source_event_id = event.source['content']['m.relates_to']['event_id']
    origin_event = await bot.api.async_client.room_get_event(config["control"]["control_room_id"], source_event_id)
    content = origin_event.event.body

    if config["control"]["dry_run"]:

        print(f"[dry_run] Sending message to control room")

        await bot.api.send_text_message(
                room_id=config["control"]["control_room_id"],
                message=content,
                msgtype="m.text")

    else:

        for room in trigger_item["destination_rooms"]:

            print(f"Sending message to room {room}")

            save_history(config, trigger, room, content),

            match room["network"]:

                case "matrix":
                    await bot.api.send_text_message(
                            room_id=room["id"],
                            message=content,
                            msgtype="m.text")

                case "signal":
                    url = 'http://localhost:8080/v2/send'
                    send_obj = {
                        "message": content,
                        "number": config["control"]["signal_origin_number"],
                        "recipients": [ room["id"] ]
                    }
                    x = requests.post(url, json = send_obj)

                case "rocketchat":
                    print("Not implemented yet")

async def send_help():
    help_message = "Available triggers:\n"

    for trigger_item in config["triggers"]:
        triggers = "".join([emoji.emojize(trigger) for trigger in trigger_item["emoji_triggers"]])
        help_message += f"{triggers} - {trigger_item['description']}\n"

    await bot.api.send_text_message(
        room_id=config["control"]["control_room_id"],
        message=help_message
    )

async def send_history():

    weekday_emojis = defaultdict(Counter)
    one_week_ago = datetime.now() - timedelta(days=7)
    with open(config["control"]["log_file"], "r") as f:
        csv_reader = csv.reader(f)
        next(csv_reader) # skip header row
        for row in csv_reader:
            timestamp_str, emoji_str = row[0], row[1]
            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S.%f")
            if timestamp >= one_week_ago:
                weekday = timestamp.weekday()
                weekday_emojis[weekday][emoji_str] += 1

    emoji_counts = []
    for weekday in range(7):
        day = datetime.now() - timedelta(days=weekday)
        day_message = [f"- {day.strftime('%A')}: "]
        counts_for_day = weekday_emojis[weekday]
        # convert to list of tuples and sort by count
        counts_for_day = sorted(counts_for_day.items(), key=lambda x: x[1], reverse=True)
        for emoji_str, count in counts_for_day:
            day_message.append(f" - {emoji.emojize(emoji_str)} {count}")
        emoji_counts.append("".join(day_message))

    history_message = "Latest week emojis:\n" + "\n".join(emoji_counts)

    await bot.api.send_text_message(
        room_id=config["control"]["control_room_id"],
        message=history_message
    )


@bot.listener.on_message_event
async def on_message(room, message):
    match = botlib.MessageMatch(room, message, bot, PREFIX)

    if match.is_not_from_this_bot() and match.prefix():

        if match.command("help"):
            await send_help()

        if match.command("history"):
            await send_history()

@bot.listener.on_reaction_event
async def on_reaction(room, event, reaction):

    trigger = emoji.demojize(reaction)
    print(f"User {event.source['sender']} reacted with {trigger}")

    for trigger_item in config["triggers"]:
        if trigger in trigger_item["emoji_triggers"]:
            await send_message(config, trigger, event, trigger_item)

bot.run()

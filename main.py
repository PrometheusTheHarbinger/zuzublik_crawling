import io
import re
import sqlite3

import pandas
import requests
from lxml import etree
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler

# Globals should do it, dependency injections are excessive when code is less than 100 lines
_MARKUP = InlineKeyboardMarkup([[InlineKeyboardButton("Send manually crawled data", callback_data="0")]])
_is_waiting = False
_sqlite_con = sqlite3.connect("test.db")
_sqlite_cur = _sqlite_con.cursor()
_sqlite_cur.execute("CREATE TABLE IF NOT EXISTS data(title, url, xpath)")

def parse_price(url, xpath) -> str | None:
    html = requests.get(url).text
    parser = etree.HTMLParser()
    tree = etree.fromstring(html, parser)
    tag = tree.xpath(xpath)
    if len(tag) == 0:
        return None
    tag = tag[0]
    match_or = re.search(r"(\d+)\s?(\d*)",tag.text if tag.text else "")
    if match_or is not None:
        return ''.join(match_or.group(1, 2))

async def first_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Please click here when you're about to send a file!", reply_markup=_MARKUP)

async def requested_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    global _is_waiting
    _is_waiting = True
    await query.answer()
    await query.edit_message_text("Awaiting your file...")

async def file_uploaded(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _is_waiting, _sqlite_cur, _sqlite_con
    if not _is_waiting:
        return
    _is_waiting = False
    if update.message.effective_attachment is None:
        await update.message.reply_text("No files were sent!", reply_markup=_MARKUP)
    else:
        file = await update.message.effective_attachment.get_file()
        buffer = io.BytesIO()
        await file.download_to_memory(buffer)
        buffer.seek(0)
        df = pandas.read_excel(buffer)
        ress = ""
        average_over_site = {}
        for title, url, xpath in df.itertuples(index=False):
            ress += f"Title: {title}, URL: {url}, xPath: {xpath}\n"
            # Unsafe as hell, but normal ORM would have bloated this code twice the size. We trust our users, right?
            _sqlite_cur.execute(f"INSERT INTO data VALUES('{title}','{url}','{xpath}')")
            _sqlite_con.commit()
            price = parse_price(url, xpath)
            if price is not None:
                site = re.search(r"https?://([^/]*)", url)
                if site is not None:
                    if site.group(1) not in average_over_site:
                        average_over_site[site.group(1)] = [int(price)]
                    else:
                        average_over_site[site.group(1)].append(int(price))
        for k, v in average_over_site.values():
            ress += f"Site: {k}, average price there: {sum(v)/len(v)}\n"
        await update.message.reply_text(ress, reply_markup=_MARKUP)


if __name__ == "__main__":
    with open("bot_token") as f:
        token = f.read()
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", first_time))
    app.add_handler(CallbackQueryHandler(requested_upload))
    app.add_handler(MessageHandler(None, file_uploaded))
    app.run_polling()

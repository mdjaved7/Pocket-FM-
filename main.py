import asyncio
import os
import time
import re
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from playwright.async_api import async_playwright

BOT_TOKEN = "8918721301:AAGQomTKJ5vtViPRyAhHAZ51_eEmJk1v25I"
USER_MOBILE = "8660060417"

sessions = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"Pocket FM ({USER_MOBILE}) लॉगिन शुरू हो रहा है... OTP का इंतज़ार करें।")

    try:
        pw = await async_playwright().start()
        
        # एंटी-डिटेक्शन फ़्लैग्स के साथ ब्राउज़र शुरू करें
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-web-security',
                '--allow-running-insecure-content'
            ]
        )
        
        # असली यूज़र जैसा व्यवहार बनाने के लिए सेटिंग्स
        context_page = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
            locale="en-US"
        )
        
        page = await context_page.new_page()
        
        # ऑटोमेशन फ़्लैग को छुपाने के लिए स्क्रिप्ट
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        await page.goto("https://pocketfm.com/login", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(5)

        # लचीला इनपुट सेलेक्टर
        input_box = await page.wait_for_selector('input[type="tel"], input[type="number"], input[name="phone"], input', timeout=25000)
        await input_box.fill(USER_MOBILE)
        await asyncio.sleep(1)

        # सबमिट बटन ढूँढकर क्लिक करें
        submit_btn = await page.query_selector('button[type="submit"], button:has-text("Continue"), button:has-text("Send OTP"), button')
        if submit_btn:
            await submit_btn.click()

        sessions[chat_id] = {"step": "WAITING_FOR_OTP", "pw": pw, "browser": browser, "page": page}
        await update.message.reply_text("OTP यहाँ टाइप करके भेजें:")
    except Exception as e:
        print("Start Error:", e)
        await update.message.reply_text("लॉगिन एरर! सर्वर द्वारा ब्लॉक किया गया या टाइमआउट हो गया। कृपया फिर से /start करें।")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    session = sessions.get(chat_id)

    if not session:
        await update.message.reply_text("कृपया पहले /start भेजें।")
        return

    # 1. OTP वेरिफिकेशन
    if session["step"] == "WAITING_FOR_OTP":
        try:
            page = session["page"]
            otp_box = await page.wait_for_selector('input[type="number"], input[type="text"], input', timeout=15000)
            await otp_box.fill(text)
            await asyncio.sleep(1)

            submit_btn = await page.query_selector('button[type="submit"], button:has-text("Verify"), button')
            if submit_btn:
                await submit_btn.click()
                
            await asyncio.sleep(5)

            session["step"] = "READY_FOR_BULK"
            await update.message.reply_text(
                "लॉगिन सफल रहा! 🎉\n\n"
                "अब शो का नाम और एपिसोड रेंज भेजें।\n\n"
                "उदाहरण:\n"
                "- Brahmyoddha Ep 42 (सिंगल एपिसोड के लिए)\n"
                "- Brahmyoddha 1-100 (1 से 100 तक रिकॉर्ड करने के लिए)"
            )
        except Exception as e:
            print("OTP Error:", e)
            await update.message.reply_text("OTP गलत है या समय समाप्त हो गया।")
        return

    # 2. एपिसोड प्रोसेसिंग
    if session["step"] == "READY_FOR_BULK":
        page = session["page"]
        show_name = text
        start_ep = 1
        end_ep = 1

        if "-" in text:
            parts = text.split(" ")
            range_parts = parts.pop().split("-")
            show_name = " ".join(parts)
            start_ep = int(range_parts[0]) if range_parts[0].isdigit() else 1
            end_ep = int(range_parts[1]) if range_parts[1].isdigit() else 1
        elif "ep" in text.lower():
            match = re.search(r"(.*)\s+ep\s*(\d+)", text, re.IGNORECASE)
            if match:
                show_name = match.group(1)
                start_ep = int(match.group(2))
                end_ep = start_ep

        await update.message.reply_text(f'"{show_name}" के Episode {start_ep} से {end_ep} तक की प्रोसेस शुरू की जा रही है...')

        for ep in range(start_ep, end_ep + 1):
            target_ep_name = f"E{ep}"
            await update.message.reply_text(f"PROCESSING: {show_name} - {target_ep_name}...")

            try:
                search_url = f"https://pocketfm.com/search?q={show_name} {target_ep_name}"
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)

                played = await page.evaluate('''
                    (epText) => {
                        const elements = Array.from(document.querySelectorAll('div, p, span, h3'));
                        const match = elements.find(el => el.textContent.toLowerCase().includes(epText.toLowerCase()));
                        if (match) {
                            const parent = match.closest('div') || match.parentElement;
                            const btn = parent.querySelector('button, svg') || match;
                            btn.click();
                            return true;
                        }
                        return false;
                    }
                ''', target_ep_name)

                if not played:
                    play_btn = await page.query_selector('button[aria-label="Play"]')
                    if play_btn:
                        await play_btn.click()

            except Exception as err:
                print(f"Error on Episode {ep}:", err)
                await update.message.reply_text(f"Episode {ep} चलाने में समस्या आई।")

        await update.message.reply_text(f"सभी एपिसोड्स ({start_ep} से {end_ep}) की प्रोसेस पूरी हो चुकी है!")

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Python Bulk Episode Bot तैयार है!")
    app.run_polling()
    

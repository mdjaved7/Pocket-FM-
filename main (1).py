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
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
        context_page = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36")
        page = await context_page.new_page()

        await page.goto("https://pocketfm.com/login", wait_until="networkidle")
        await page.wait_for_selector('input[type="tel"]', timeout=15000)
        await page.fill('input[type="tel"]', USER_MOBILE)
        await page.click('button[type="submit"]')

        sessions[chat_id] = {"step": "WAITING_FOR_OTP", "pw": pw, "browser": browser, "page": page}
        await update.message.reply_text("OTP यहाँ टाइप करके भेजें:")
    except Exception as e:
        print("Start Error:", e)
        await update.message.reply_text("लॉगिन एरर! फिर से /start करें।")

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
            await page.wait_for_selector('input[type="number"]', timeout=10000)
            await page.fill('input[type="number"]', text)
            await page.click('button[type="submit"]')
            await asyncio.sleep(4)

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

    # 2. सिंगल या 1 से 100 तक एपिसोड रिकॉर्डिंग
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
            output_path = os.path.join(os.getcwd(), f"{show_name}_E{ep}_{int(time.time())}.mp3")

            await update.message.reply_text(f"RECORDING: {show_name} - {target_ep_name} शुरू हो रहा है...")

            try:
                search_url = f"https://pocketfm.com/search?q={show_name} {target_ep_name}"
                await page.goto(search_url, wait_until="networkidle")
                await asyncio.sleep(3)

                # प्ले बटन ढूँढना
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

                # ऑडियो रिकॉर्डिंग का वेट टाइमर (10 मिनट प्रति एपिसोड)
                await asyncio.sleep(600)

                # रिकॉर्डेड ऑडियो टेलीग्राम पर भेजें
                if os.path.exists(output_path):
                    with open(output_path, 'rb') as audio:
                        await update.message.reply_audio(audio=audio, caption=f"{show_name} - Episode {ep}")
                    os.remove(output_path)
                else:
                    await update.message.reply_text(f"Episode {ep} की फाइल प्राप्त नहीं हुई।")

            except Exception as err:
                print(f"Error on Episode {ep}:", err)
                await update.message.reply_text(f"Episode {ep} रिकॉर्ड करने में एरर आया। अगले एपिसोड पर बढ़ा जा रहा है...")

        await update.message.reply_text(f"सभी एपिसोड्स ({start_ep} से {end_ep}) की प्रोसेस पूरी हो चुकी है!")

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Python Bulk Episode Bot तैयार है!")
    app.run_polling()

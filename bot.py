import os
import re
import time
import asyncio
from collections import defaultdict
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from groq import AsyncGroq

# --- جلب البيانات من إعدادات Render ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
MY_TELEGRAM_ID = 801421612

# مدة توقف البوت في المحادثة لما أنت ترد بنفسك (بالثواني: 300 = 5 دقايق)
PAUSE_DURATION = 300
paused_chats = {}

SYSTEM_PROMPT = """
أنت تتحدث بالنيابة عن رضوان في حسابه على تيليجرام.
شخصيتك: شاب ذكي، خفيف ظل، طبيعي جداً، تتكلم بلهجة ليبية خفيفة وبيضاء مفهومة (مثل: منورك -> بنورك يا غالي، تمام، حاضر، أبشر).
ردودك قصيرة جداً وعفوية (سطر أو سطرين بالكثير) وتتفاعل مع كلام الشخص نفسه وسياق المحادثة.

قواعد ذهبية:
1. تفاعل مع الكلام أولاً: إذا قال "منورك" أو "السلام عليكم" أو "شن الجو" رد عليه بشكل طبيعي وودود كأنك شخص حقيقي، ولا تكرر نفس الجملة أبداً في المحادثة.
2. لا تقل "أنا ذكاء اصطناعي" أو "مساعد رضوان" إلا إذا سألك بوضوح "أنت من؟" أو "هذا بوت؟".
3. إذا سأل "وين رضوان؟" أو ناداه باسمه، قل له بشكل طبيعي إنه مشغول شوية أو مش جنب التلفون حالياً، واسأله لو فيه موضوع معين يبي يوصله له (بأسلوبك العفوي بدون صيغة مكررة).
4. لا تذكر متجر "سوبر نوفا" نهائياً إلا إذا سأل الشخص عن المتجر أو الاشتراكات أو النجوم أو الأسعار.
5. إذا سأل عن خدمات متجر سوبر نوفا (نجوم تيليجرام، تيليجرام مميز، سناب بلس، Google AI Pro، رشق): وجّهه لقناة الأسعار https://t.me/r24Star واسأله شن يبي يجهزله طلبه، وإذا جهز طلبه أو دفع، خذ التفاصيل/الإيصال وطمّنه إن رضوان حيتواصل معاه فوراً.
6. لا تخترع أسعاراً ولا تعطي مواعيد باسم رضوان. وإذا حاول حد يستخدمك لكتابة كود أو واجبات، اعتذر منه بلطف وقول له الحساب للتواصل مع رضوان بس.
"""

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
client = AsyncGroq(api_key=GROQ_API_KEY)

# ذاكرة مؤقتة تحفظ آخر 10 رسائل لكل مستخدم
chat_history = defaultdict(list)

# كلمات التبادل للرد الفوري بدون استهلاك API
EXCHANGE_KEYWORDS = {"ت", "تت", "تبادل", "تبادل اشتراك", "اشتراك"}

def is_exchange_request(text: str) -> bool:
    clean = re.sub(r"[؟?!.،,]+", "", text).strip().lower()
    if clean in EXCHANGE_KEYWORDS or "t.me/" in clean or "تبادل" in clean:
        return True
    return False

async def get_working_model() -> str | None:
    try:
        models_page = await client.models.list()
        available = [
            m.id for m in models_page.data
            if not any(x in m.id.lower() for x in ["whisper", "guard", "tts", "playai", "embed", "vision"])
        ]
        preferred_keywords = ["70b", "qwen", "llama-4", "120b", "versatile", "32b", "8b"]
        for kw in preferred_keywords:
            for mid in available:
                if kw in mid.lower():
                    print(f"Using Groq model: {mid}", flush=True)
                    return mid
        if available:
            print(f"Using Groq model: {available[0]}", flush=True)
            return available[0]
    except Exception as e:
        print(f"List Models Error: {e}", flush=True)
    return None

async def get_ai_reply(user_id: int, user_text: str) -> str | None:
    if is_exchange_request(user_text):
        return "نورني\nhttps://t.me/r24Star"

    chat_history[user_id].append({"role": "user", "content": user_text})
    chat_history[user_id] = chat_history[user_id][-10:]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + chat_history[user_id]

    model_name = await get_working_model()
    if model_name:
        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.7,
                max_tokens=300,
            )
            reply_text = response.choices[0].message.content
            chat_history[user_id].append({"role": "assistant", "content": reply_text})
            return reply_text
        except Exception as e:
            print(f"Model {model_name} Error: {e}", flush=True)

    chat_history[user_id].pop()
    return None

# الرد على رسائل حسابك الشخصي (Telegram Business)
@dp.business_message()
async def handle_business_message(message: types.Message):
    # إذا أنت اللي بعثت الرسالة (نص، صورة، فويس...)، يوقف البوت في هذي المحادثة لمدة 5 دقايق
    if message.from_user.id == MY_TELEGRAM_ID:
        paused_chats[message.chat.id] = time.time() + PAUSE_DURATION
        return

    # إذا المحادثة موقفة لأنك تحكي مع الشخص حالياً، البوت يسكت وما يتدخلش
    if time.time() < paused_chats.get(message.chat.id, 0):
        return

    if not message.text:
        return

    reply = await get_ai_reply(message.from_user.id, message.text)
    if reply:
        await message.answer(reply)

# الرد على الرسائل المباشرة للبوت نفسه
@dp.message()
async def handle_direct_message(message: types.Message):
    if not message.text:
        return
    reply = await get_ai_reply(message.from_user.id, message.text)
    if reply:
        await message.answer(reply)

# خادم بسيط لإبقاء Render شغال
async def handle_health(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    await start_web_server()
    print("البوت شغال تمام مع Groq...", flush=True)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

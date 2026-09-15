"""Zavod Hisob Telegram handlers."""
from datetime import date
from decimal import Decimal,InvalidOperation
from telegram import ReplyKeyboardMarkup,Update
from telegram.ext import Application,CommandHandler,ContextTypes,ConversationHandler,MessageHandler,filters
from bot import db

DB_KEY="db";REDIS_KEY="redis";CANCEL="🚫 Bekor qilish";YES="✅ Ha";NO="❌ Yo‘q"
ADD="📥 Yuk qabul qilish";FURNACE="🔥 Qozonga berilgan mahsulotlar";FINISHED="🏭 Tayyor mahsulot";SCRAP="♻️ Chiqit ombori";RAW="📦 Xomashyo ombori";SALE="💰 Sotuv";REPORT="📊 Umumiy hisob";EXP="⚙️ Xarajatlar"
LOAD_PRODUCTS=["Qizil oddiy","Qizil Lahim","Tros","Sariq","Karbyurator","Qizil radiator","Sariq radiator","Sink quyma","Teplo","Alyumin zapchast","Alyumin chushka"]
FURN={"mis":["Qizil","Qizil Lahim","Tros"],"latun":["Sariq","Karbyurator","Qizil radiator","Sariq radiator","Sink quyma","Qizil S-K"],"alyumin":["Alyumin zapchast","Alyumin chushka"]}
PROD={"mis":["Mis truba"],"latun":["Latun truba","Latun uzuk"],"alyumin":["Alyumin uzuk"]}
SCR={"mis":"Mis chiqiti","latun":"Latun chiqiti","alyumin":"Alyumin chiqiti"}
EXPS=["👷 Ishchilar","⚡ Elektr","🔥 Gaz","🚚 Transport","🛠 Ta’mirlash","🍽️ Ovqat","➕ Boshqa xarajat"]

def menu(): return ReplyKeyboardMarkup([[ADD],[FURNACE],[FINISHED],[SCRAP],[RAW],[SALE],[REPORT],[EXP]],resize_keyboard=True)
def kb(xs,extra=None):
    b=[[x] for x in xs]
    if extra:b.append([extra])
    b.append([CANCEL]);return ReplyKeyboardMarkup(b,resize_keyboard=True)
def yn():return ReplyKeyboardMarkup([[YES,NO],[CANCEL]],resize_keyboard=True)
def p(c):return c.application.bot_data.get(DB_KEY)
def n(v):
    try:
        x=Decimal(str(v).replace(" ","").replace(",","."));return x if x>0 else None
    except (InvalidOperation,ValueError):return None
def kg(v):return db.fmt_kg(v)

async def start(u,c):
    if p(c):await db.upsert_user(p(c),u.effective_user.id,u.effective_user.username,u.effective_user.first_name)
    await u.message.reply_text("🏭 Zavod Hisob botiga xush kelibsiz.",reply_markup=menu())
async def cancel(u,c):
    c.user_data.clear();await u.message.reply_text("Bekor qilindi.",reply_markup=menu());return ConversationHandler.END
async def set_bot_commands(app):await app.bot.set_my_commands([("start","Asosiy menyu"),("help","Yordam"),("cancel","Bekor qilish")])
async def error_handler(update,context): print("BOT ERROR:",context.error)

async def active(c,u):
    d=date.today()
    if p(c):
        x=await db.get_active_date(p(c),u.effective_user.id,d)
        if x:return x
        await db.set_active_date(p(c),u.effective_user.id,d)
    return d

# Yuk qabul qilish
LVEH,LPER,LMAT,LCUS,LKG,LPRI,LSKI,LRET,LMORE,LCONF=range(10)
async def load_start(u,c):
    d=await active(c,u);c.user_data["load"]={"date":d,"items":[]}
    await u.message.reply_text(f"📅 Sana: {d:%d.%m.%Y}\n🚚 Mashina raqamini kiriting:",reply_markup=kb([]));return LVEH
async def load_veh(u,c):c.user_data["load"]["vehicle"]=u.message.text.strip();await u.message.reply_text("👤 Ismi familiyasini kiriting:",reply_markup=kb([]));return LPER
async def load_per(u,c):c.user_data["load"]["person"]=u.message.text.strip();await u.message.reply_text("📦 Mahsulotni tanlang:",reply_markup=kb(LOAD_PRODUCTS,"➕ Boshqa mahsulot"));return LMAT
async def load_mat(u,c):
    t=u.message.text.strip()
    if t=="➕ Boshqa mahsulot":await u.message.reply_text("📦 Mahsulot nomini yozing:",reply_markup=kb([]));return LCUS
    if t not in LOAD_PRODUCTS:return LMAT
    c.user_data["load"]["cur"]=t;await u.message.reply_text("⚖️ Kg kiriting:",reply_markup=kb([]));return LKG
async def load_cus(u,c):c.user_data["load"]["cur"]=u.message.text.strip();await u.message.reply_text("⚖️ Kg kiriting:",reply_markup=kb([]));return LKG
async def load_kg(u,c):
    x=n(u.message.text)
    if not x:await u.message.reply_text("Kg noto‘g‘ri.");return LKG
    c.user_data["load"]["kg"]=x;await u.message.reply_text("💵 1 kg narxini so‘mda kiriting:",reply_markup=kb([]));return LPRI
async def load_pri(u,c):
    x=n(u.message.text)
    if not x:await u.message.reply_text("Narx noto‘g‘ri.");return LPRI
    c.user_data["load"]["price"]=x;await u.message.reply_text("📉 Skidka foizi (yo‘q bo‘lsa 0):",reply_markup=kb([]));return LSKI
async def load_ski(u,c):
    try:x=Decimal(u.message.text.replace(",","."));assert 0<=x<=100
    except:await u.message.reply_text("0–100 foiz kiriting.");return LSKI
    c.user_data["load"]["skidka"]=x;await u.message.reply_text("↩️ Vozvrat kg (yo‘q bo‘lsa 0):",reply_markup=kb([]));return LRET
async def load_ret(u,c):
    try:x=Decimal(u.message.text.replace(",","."));assert 0<=x<=c.user_data["load"]["kg"]
    except:await u.message.reply_text("Vozvrat kg noto‘g‘ri.");return LRET
    d=c.user_data["load"];d["return"]=x;d["items"].append({"material":d.pop("cur"),"kg":d.pop("kg"),"price":d.pop("price"),"skidka_pct":d.pop("skidka"),"vozvrat_kg":d.pop("return")})
    await u.message.reply_text("➕ Yana mahsulot qo‘shasiz?",reply_markup=yn());return LMORE
async def load_more(u,c):
    if u.message.text==YES:await u.message.reply_text("📦 Keyingi mahsulot:",reply_markup=kb(LOAD_PRODUCTS,"➕ Boshqa mahsulot"));return LMAT
    if u.message.text!=NO:return LMORE
    d=c.user_data["load"];total=0;pay=0;lines=[]
    for x in d["items"]:
        gross=float(x["kg"]);ret=float(x["vozvrat_kg"]);pct=float(x["skidka_pct"]);pk=gross*(1-pct/100)-ret;amt=pk*float(x["price"])
        total+=gross;pay+=amt;lines.append(f"• {x['material']} — {kg(gross)} kg | {float(x['price']):,.0f} so‘m/kg | skidka {pct:g}% | vozvrat {kg(ret)} kg | {amt:,.0f} so‘m")
    d["pay"]=pay
    await u.message.reply_text("📋 Yuk xulosasi\n🚚 "+d["vehicle"]+"\n👤 "+d["person"]+"\n"+"\n".join(lines)+f"\n\n⚖️ Jami: {kg(total)} kg\n💰 To‘lanadi: {pay:,.0f} so‘m",reply_markup=yn());return LCONF
async def load_conf(u,c):
    if u.message.text==NO:
        await u.message.reply_text("❌ Hozirgi bosqichda xulosani bekor qilib, qayta kiritish mumkin.",reply_markup=menu());c.user_data.clear();return ConversationHandler.END
    if u.message.text!=YES:return LCONF
    d=c.user_data["load"]
    try:no=await db.create_load(p(c),d["date"],d["vehicle"],d["person"],d["items"])
    except Exception as e:await u.message.reply_text(f"❌ {e}",reply_markup=menu());c.user_data.clear();return ConversationHandler.END
    t,count=await db.daily_load_total(p(c),d["date"])
    await u.message.reply_text(f"✅ Yuk #{no[1]} saqlandi.\n🚛 Bugungi yuklar: {count} ta\n⚖️ Jami: {kg(t)} kg ({t/1000:.3f} tonna)",reply_markup=menu());c.user_data.clear();return ConversationHandler.END

# Qozon
FKIND,FMAT,FKG,FMORE,FCONF=range(10,15)
async def furnace_start(u,c):await u.message.reply_text("Qaysi qozon?",reply_markup=kb(["🔥 Mis qozon","🔥 Latun qozon","🔥 Alyumin qozon"]));return FKIND
async def furnace_kind(u,c):
    t=u.message.text;kind="mis" if "Mis" in t else "latun" if "Latun" in t else "alyumin";c.user_data["furnace"]={"kind":kind,"date":await active(c,u),"items":[]}
    await u.message.reply_text("📦 Materialni tanlang:",reply_markup=kb(FURN[kind],"➕ Boshqa material"));return FMAT
async def furnace_mat(u,c):
    d=c.user_data["furnace"];t=u.message.text.strip()
    if t=="➕ Boshqa material":await u.message.reply_text("✍️ Material nomini yozing:",reply_markup=kb([]));return FMAT
    if t not in FURN[d["kind"]]:
        # Custom typed material is accepted only if it exists in raw warehouse.
        if await db.material_stock(p(c),t)<=0:await u.message.reply_text("Bu material xomashyo omborida yo‘q.");return FMAT
    d["cur"]=t;await u.message.reply_text("⚖️ Necha kg?",reply_markup=kb([]));return FKG
async def furnace_kg(u,c):
    x=n(u.message.text);d=c.user_data["furnace"]
    if not x:await u.message.reply_text("Kg noto‘g‘ri.");return FKG
    av=await db.material_stock(p(c),d["cur"])
    if float(x)>av+.0001:await u.message.reply_text(f"❌ Omborda faqat {kg(av)} kg bor.");return FKG
    d["items"].append({"material":d.pop("cur"),"kg":x});await u.message.reply_text("➕ Yana material?",reply_markup=yn());return FMORE
async def furnace_more(u,c):
    d=c.user_data["furnace"]
    if u.message.text==YES:await u.message.reply_text("📦 Materialni tanlang:",reply_markup=kb(FURN[d["kind"]],"➕ Boshqa material"));return FMAT
    if u.message.text!=NO:return FMORE
    s=sum(float(x["kg"]) for x in d["items"]);await u.message.reply_text("📋 Qozon xulosasi\n"+"\n".join(f"• {x['material']}: {kg(x['kg'])} kg" for x in d["items"])+f"\n⚖️ Jami: {kg(s)} kg\n\nSaqlaymizmi?",reply_markup=yn());return FCONF
async def furnace_conf(u,c):
    if u.message.text!=YES:return FCONF
    d=c.user_data["furnace"]
    try:fid=await db.create_furnace(p(c),d["date"],d["kind"],d["items"])
    except Exception as e:await u.message.reply_text(f"❌ {e}",reply_markup=menu());c.user_data.clear();return ConversationHandler.END
    await u.message.reply_text(f"✅ Qozon #{fid} saqlandi.\n📦 Xomashyo omboridan kamaydi.\n🏭 Tayyor mahsulot chiqishini keyin kiriting.",reply_markup=menu());c.user_data.clear();return ConversationHandler.END

# Tayyor mahsulot
OF,ON,OP,OK,OC=range(20,25)
async def out_start(u,c):await u.message.reply_text("Qaysi qozon?",reply_markup=kb(["🔥 Mis","🔥 Latun","🔥 Alyumin"]));return OF
async def out_f(u,c):
    t=u.message.text;kind="mis" if "Mis" in t else "latun" if "Latun" in t else "alyumin";c.user_data["out"]={"kind":kind,"date":await active(c,u)}
    rows=await db.furnace_list(p(c),kind)
    nums=[f"#{r['id']}" for r in rows]
    await u.message.reply_text("Qozon raqamini tanlang yoki yozing:\n"+(" ".join(nums) if nums else "Qozon yo‘q"),reply_markup=kb([]));return ON
async def out_n(u,c):
    try:i=int(u.message.text.replace("#","").strip())
    except:await u.message.reply_text("Qozon raqami noto‘g‘ri.");return ON
    c.user_data["out"]["fid"]=i;kind=c.user_data["out"]["kind"];await u.message.reply_text("🏭 Tayyor mahsulotni tanlang:",reply_markup=kb(PROD[kind]));return OP
async def out_p(u,c):c.user_data["out"]["product"]=u.message.text;await u.message.reply_text("⚖️ Kg:",reply_markup=kb([]));return OK
async def out_k(u,c):
    x=n(u.message.text)
    if not x:return OK
    c.user_data["out"]["kg"]=x;await u.message.reply_text(f"📋 {c.user_data['out']['product']} — {kg(x)} kg\nSaqlaymizmi?",reply_markup=yn());return OC
async def out_c(u,c):
    if u.message.text!=YES:return OC
    d=c.user_data["out"]
    try:await db.create_output(p(c),d["date"],d["fid"],d["product"],d["kg"])
    except Exception as e:await u.message.reply_text(f"❌ {e}",reply_markup=menu());c.user_data.clear();return ConversationHandler.END
    await u.message.reply_text("✅ Tayyor mahsulot omboriga qo‘shildi.",reply_markup=menu());c.user_data.clear();return ConversationHandler.END

# Sotuv
SB,SP,SK,SPr,SM,SC=range(30,36)
async def sale_start(u,c):c.user_data["sale"]={"date":await active(c,u),"items":[]};await u.message.reply_text("👤 Xaridor ismini kiriting:",reply_markup=kb([]));return SB
async def sale_b(u,c):c.user_data["sale"]["buyer"]=u.message.text.strip();await u.message.reply_text("🏭 Mahsulot:",reply_markup=kb(["Mis truba","Latun truba","Latun uzuk","Alyumin uzuk"]));return SP
async def sale_p(u,c):c.user_data["sale"]["product"]=u.message.text;await u.message.reply_text("⚖️ Kg:",reply_markup=kb([]));return SK
async def sale_k(u,c):
    x=n(u.message.text)
    if not x:return SK
    av=await db.finished_stock_one(p(c),c.user_data["sale"]["product"])
    if float(x)>av+.0001:await u.message.reply_text(f"❌ Omborda {kg(av)} kg bor.");return SK
    c.user_data["sale"]["kg"]=x;await u.message.reply_text("💵 1 kg sotuv narxi (so‘m):",reply_markup=kb([]));return SPr
async def sale_pr(u,c):
    x=n(u.message.text)
    if not x:return SPr
    d=c.user_data["sale"];d["items"].append({"product":d.pop("product"),"kg":d.pop("kg"),"price":x});await u.message.reply_text("➕ Yana mahsulot?",reply_markup=yn());return SM
async def sale_m(u,c):
    if u.message.text==YES:await u.message.reply_text("🏭 Mahsulot:",reply_markup=kb(["Mis truba","Latun truba","Latun uzuk","Alyumin uzuk"]));return SP
    if u.message.text!=NO:return SM
    d=c.user_data["sale"];rev=sum(float(x["kg"])*float(x["price"]) for x in d["items"]);await u.message.reply_text("📋 Sotuv xulosasi\n"+"\n".join(f"• {x['product']} — {kg(x['kg'])} kg × {float(x['price']):,.0f} = {float(x['kg'])*float(x['price']):,.0f} so‘m" for x in d["items"])+f"\n\n💰 Jami: {rev:,.0f} so‘m",reply_markup=yn());return SC
async def sale_c(u,c):
    if u.message.text!=YES:return SC
    d=c.user_data["sale"]
    try:no,rev=await db.create_sale(p(c),d["date"],d["buyer"],d["items"])
    except Exception as e:await u.message.reply_text(f"❌ {e}",reply_markup=menu());c.user_data.clear();return ConversationHandler.END
    await u.message.reply_text(f"✅ Sotuv #{no} saqlandi.\n💰 {rev:,.0f} so‘m",reply_markup=menu());c.user_data.clear();return ConversationHandler.END

# Xarajat
EC,EX,EA,EN,ECF=range(40,45)
async def exp_start(u,c):await u.message.reply_text("⚙️ Xarajat turini tanlang:",reply_markup=kb(EXPS));return EC
async def exp_c(u,c):
    if u.message.text=="➕ Boshqa xarajat":await u.message.reply_text("Xarajat nomini yozing:",reply_markup=kb([]));return EX
    c.user_data["exp"]={"date":await active(c,u),"cat":u.message.text};await u.message.reply_text("💰 Summani so‘mda kiriting:",reply_markup=kb([]));return EA
async def exp_x(u,c):c.user_data["exp"]={"date":await active(c,u),"cat":u.message.text};await u.message.reply_text("💰 Summani so‘mda kiriting:",reply_markup=kb([]));return EA
async def exp_a(u,c):
    x=n(u.message.text)
    if not x:return EA
    c.user_data["exp"]["amount"]=x;await u.message.reply_text("📝 Izoh (bo‘lmasa -):",reply_markup=kb([]));return EN
async def exp_n(u,c):
    d=c.user_data["exp"];d["note"]=u.message.text;await u.message.reply_text(f"📋 {d['cat']}\n💰 {float(d['amount']):,.0f} so‘m\n📝 {d['note']}\n\nSaqlaymizmi?",reply_markup=yn());return ECF
async def exp_cf(u,c):
    if u.message.text!=YES:return ECF
    d=c.user_data["exp"]
    try:no=await db.create_expense(p(c),d["date"],d["cat"],d["amount"],d["note"])
    except Exception as e:await u.message.reply_text(f"❌ {e}",reply_markup=menu());c.user_data.clear();return ConversationHandler.END
    await u.message.reply_text(f"✅ Xarajat #{no} saqlandi.",reply_markup=menu());c.user_data.clear();return ConversationHandler.END

async def raw(u,c):
    r=await db.raw_stock(p(c));await u.message.reply_text("📦 Xomashyo ombori\n\n"+("\n".join(f"• {x['material']}: {kg(x['kg'])} kg" for x in r) or "Bo‘sh."),reply_markup=menu())
async def fin(u,c):
    r=await db.finished_stock(p(c));await u.message.reply_text("🏭 Tayyor mahsulot\n\n"+("\n".join(f"• {x['product']}: {kg(x['kg'])} kg" for x in r) or "Bo‘sh."),reply_markup=menu())
async def scr(u,c):
    r=await db.scrap_stock(p(c));await u.message.reply_text("♻️ Chiqit ombori\n\n"+("\n".join(f"• {x['scrap_type']}: {kg(x['kg'])} kg" for x in r) or "Bo‘sh."),reply_markup=menu())
async def rep(u,c):
    d=date.today();r=await db.report(p(c),d,d);await u.message.reply_text(f"📊 Umumiy hisob — {d:%d.%m.%Y}\n\n🚛 Yuklar: {r['loads']} ta\n⚖️ Kirim: {kg(r['incoming_kg'])} kg\n💰 Sotuv: {r['revenue']:,.0f} so‘m\n⚙️ Xarajatlar: {r['expenses']:,.0f} so‘m\n\n🟢 Sotuv − xarajat: {r['revenue']-r['expenses']:,.0f} so‘m",reply_markup=menu())

def register_handlers(app):
    app.add_handler(CommandHandler("start",start));app.add_handler(CommandHandler("help",start))
    convs=[
      ConversationHandler(entry_points=[MessageHandler(filters.Regex(f"^{ADD}$"),load_start)],states={
       LVEH:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),load_veh)],LPER:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),load_per)],
       LMAT:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),load_mat)],LCUS:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),load_cus)],
       LKG:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),load_kg)],LPRI:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),load_pri)],
       LSKI:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),load_ski)],LRET:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),load_ret)],
       LMORE:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),load_more)],LCONF:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),load_conf)]},
       fallbacks=[MessageHandler(filters.Regex(f"^{CANCEL}$"),cancel)]),
      ConversationHandler(entry_points=[MessageHandler(filters.Regex(f"^{FURNACE}$"),furnace_start)],states={
       FKIND:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),furnace_kind)],FMAT:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),furnace_mat)],
       FKG:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),furnace_kg)],FMORE:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),furnace_more)],
       FCONF:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),furnace_conf)]},fallbacks=[MessageHandler(filters.Regex(f"^{CANCEL}$"),cancel)]),
      ConversationHandler(entry_points=[MessageHandler(filters.Regex(f"^{FINISHED}$"),out_start)],states={
       OF:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),out_f)],ON:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),out_n)],
       OP:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),out_p)],OK:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),out_k)],
       OC:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),out_c)]},fallbacks=[MessageHandler(filters.Regex(f"^{CANCEL}$"),cancel)]),
      ConversationHandler(entry_points=[MessageHandler(filters.Regex(f"^{SALE}$"),sale_start)],states={
       SB:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),sale_b)],SP:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),sale_p)],
       SK:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),sale_k)],SPr:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),sale_pr)],
       SM:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),sale_m)],SC:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),sale_c)]},fallbacks=[MessageHandler(filters.Regex(f"^{CANCEL}$"),cancel)]),
      ConversationHandler(entry_points=[MessageHandler(filters.Regex(f"^{EXP}$"),exp_start)],states={
       EC:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),exp_c)],EX:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),exp_x)],
       EA:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),exp_a)],EN:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),exp_n)],
       ECF:[MessageHandler(filters.TEXT & ~filters.Regex(f"^{CANCEL}$"),exp_cf)]},fallbacks=[MessageHandler(filters.Regex(f"^{CANCEL}$"),cancel)])
    ]
    for x in convs:app.add_handler(x)
    for text,fn in [(RAW,raw),(SCRAP,scr),(REPORT,rep)]:app.add_handler(MessageHandler(filters.Regex(f"^{text}$"),fn))
    app.add_handler(MessageHandler(filters.Regex(f"^{CANCEL}$"),cancel))

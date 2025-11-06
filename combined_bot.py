import os
import discord
from discord.ext import commands
import random
import requests
import json
from typing import Literal
from datetime import datetime, timezone
from flask import Flask, request, jsonify
import threading
import asyncio

print("🚀 Starting combined Discord bot and API server...")

# ========== CONFIGURATION ==========
DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')

if not DISCORD_BOT_TOKEN:
    print("❌ CRITICAL: DISCORD_BOT_TOKEN environment variable is not set!")
    exit(1)

CODES_FILE = "redeem_codes.json"
ORDERS_FILE = "orders.json"
PAYMENT_TARGET = "number27"
ADMIN_IDS = os.getenv('ADMIN_IDS', '1388619131984806039').split(',')
PREMIUM_ROLE_ID = int(os.getenv('PREMIUM_ROLE_ID', '1283132591553380479'))
VERIFICATION_CHANNEL_ID = int(os.getenv('VERIFICATION_CHANNEL_ID', '1420479936715554928'))
GUILD_ID = int(os.getenv('GUILD_ID', '1417458795461869670'))

print("✅ Environment variables loaded successfully")

# Get public URL from Railway
PORT = int(os.getenv('PORT', 5000))
RAILWAY_PUBLIC_URL = os.getenv('RAILWAY_STATIC_URL')

if RAILWAY_PUBLIC_URL:
    API_URL = f"https://{RAILWAY_PUBLIC_URL}"
else:
    API_URL = f"http://localhost:{PORT}"

print(f"🌐 Public URL: {RAILWAY_PUBLIC_URL}")
print(f"🔧 API URL: {API_URL}")
print(f"🔧 PORT: {PORT}")

# Initialize Discord bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Initialize Flask app
flask_app = Flask(__name__)

# Initialize data files
if not os.path.exists(CODES_FILE):
    with open(CODES_FILE, 'w') as f:
        json.dump({"codes": []}, f)

if not os.path.exists(ORDERS_FILE):
    with open(ORDERS_FILE, 'w') as f:
        json.dump({}, f)

# ========== HELPER FUNCTIONS ==========
def is_admin(user_id):
    return str(user_id) in ADMIN_IDS

def load_orders():
    try:
        with open(ORDERS_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def save_orders(orders):
    with open(ORDERS_FILE, 'w') as f:
        json.dump(orders, f, indent=2)

def load_codes():
    try:
        with open(CODES_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {"codes": []}

def save_codes(codes):
    with open(CODES_FILE, 'w') as f:
        json.dump(codes, f, indent=2)

async def send_bot_message(discord_id, amount, plan, minecraft_username=None, order_id=None):
    """Send message using bot"""
    try:
        channel = bot.get_channel(VERIFICATION_CHANNEL_ID)
        if not channel:
            print(f"Verification channel {VERIFICATION_CHANNEL_ID} not found")
            return None

        embed = discord.Embed(
            title="🛒 Payment Verification Required",
            color=0xFFA500,
            description="**React with ✅ to verify this payment**",
            timestamp=datetime.now(timezone.utc)
        )
        
        embed.add_field(name="Discord User", value=f"<@{discord_id}>", inline=True)
        if minecraft_username:
            embed.add_field(name="Minecraft Username", value=f"```{minecraft_username}```", inline=True)
        embed.add_field(name="Amount", value=f"```{amount:,}```", inline=True)
        embed.add_field(name="Plan", value=f"```{plan}```", inline=True)
        embed.add_field(name="Order ID", value=f"```{order_id}```", inline=False)
        
        message = await channel.send(embed=embed)
        await message.add_reaction("✅")
        
        print(f"✅ Verification message sent for order {order_id}")
        return message
        
    except Exception as e:
        print(f"Error sending verification message: {e}")
        return None

# ========== FLASK ROUTES ==========
@flask_app.route('/')
def home():
    return jsonify({"status": "online", "service": "Discord Bot API", "timestamp": datetime.now().isoformat()})

@flask_app.route('/health')
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

@flask_app.route('/create_order', methods=['POST'])
def create_order():
    try:
        data = request.get_json()
        print(f"📥 Received create_order request: {data}")
        
        if not data:
            return jsonify({"status": "error", "message": "No JSON data received"}), 400

        required = ['discord_id', 'amount', 'days', 'plan', 'is_code_redemption']
        if not all(field in data for field in required):
            error_msg = f"Missing required fields: {required}"
            print(f"❌ {error_msg}")
            return jsonify({"status": "error", "message": error_msg}), 400

        orders = load_orders()
        order_id = f"order_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        orders[order_id] = {
            **data,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }
        
        save_orders(orders)
        print(f"✅ Order created: {order_id}")
        return jsonify({"status": "success", "order_id": order_id})
    
    except Exception as e:
        print(f"❌ Order creation failed: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@flask_app.route('/verify_payment', methods=['POST'])
def verify_payment():
    try:
        data = request.get_json()
        print(f"📥 Received verify_payment request: {data}")
        
        if not data:
            return jsonify({"status": "error", "message": "No JSON data received"}), 400

        required = ['minecraft_username', 'amount', 'recipient']
        if not all(field in data for field in required):
            error_msg = f"Missing required fields: {required}"
            print(f"❌ {error_msg}")
            return jsonify({"status": "error", "message": error_msg}), 400

        orders = load_orders()
        
        # Find matching pending order by amount
        matching_order = None
        order_id = None
        
        for oid, order in orders.items():
            if (order.get("amount") == data["amount"] and 
                order.get("status") == "pending" and
                not order.get("is_code_redemption", False)):
                matching_order = order
                order_id = oid
                break
        
        if matching_order:
            # Update order status
            orders[order_id].update({
                "status": "paid",
                "paid_at": datetime.now().isoformat(),
                "minecraft_username": data["minecraft_username"],
                "payment_details": data
            })
            
            save_orders(orders)
            
            print(f"💰 Payment detected - Order: {order_id}, User: {matching_order['discord_id']}, Amount: {matching_order['amount']}, Plan: {matching_order['plan']}")
            
            # Send verification message to Discord
            asyncio.run_coroutine_threadsafe(
                send_bot_message(
                    matching_order["discord_id"],
                    matching_order["amount"],
                    matching_order["plan"],
                    data["minecraft_username"],
                    order_id
                ),
                bot.loop
            )
            
            return jsonify({"status": "success", "order_id": order_id})
        
        print(f"❌ No matching order found for amount: {data['amount']}")
        return jsonify({"status": "not_found", "message": "No matching pending order found for this amount"}), 404
    
    except Exception as e:
        print(f"❌ Payment verification failed: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@flask_app.route('/find_order_by_amount', methods=['POST'])
def find_order_by_amount():
    """Alternative endpoint for Minecraft mod to find orders by amount"""
    try:
        data = request.get_json()
        print(f"🔍 Received find_order request: {data}")
        
        if not data:
            return jsonify({"status": "error", "message": "No JSON data received"}), 400

        required = ['amount']
        if not all(field in data for field in required):
            return jsonify({"status": "error", "message": "Missing amount field"}), 400

        amount = data['amount']
        orders = load_orders()
        
        # Find pending orders with this amount
        matching_orders = []
        for order_id, order in orders.items():
            if (order.get("amount") == amount and 
                order.get("status") == "pending" and
                not order.get("is_code_redemption", False)):
                matching_orders.append({
                    "order_id": order_id,
                    "discord_id": order.get("discord_id"),
                    "plan": order.get("plan"),
                    "days": order.get("days"),
                    "created_at": order.get("created_at")
                })
        
        print(f"🔍 Found {len(matching_orders)} matching orders for amount {amount}")
        return jsonify({
            "status": "success", 
            "matches": matching_orders,
            "count": len(matching_orders)
        })
        
    except Exception as e:
        print(f"❌ Find order failed: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@flask_app.route('/direct_payment', methods=['POST'])
def direct_payment():
    """Direct payment endpoint that doesn't require pre-existing order"""
    try:
        data = request.get_json()
        print(f"💰 Received direct_payment request: {data}")
        
        if not data:
            return jsonify({"status": "error", "message": "No JSON data received"}), 400

        required = ['minecraft_username', 'amount', 'recipient']
        if not all(field in data for field in required):
            error_msg = f"Missing required fields: {required}"
            print(f"❌ {error_msg}")
            return jsonify({"status": "error", "message": error_msg}), 400

        # Create a new order for this payment
        orders = load_orders()
        order_id = f"direct_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Try to find which plan this amount corresponds to
        amount = data['amount']
        plan = "Unknown"
        days = 1
        
        # Define price ranges for plans
        plan_ranges = {
            "1d": (19_000_000, 20_000_000),
            "7d": (49_000_000, 50_000_000), 
            "30d": (119_000_000, 120_000_000),
            "90d": (199_000_000, 200_000_000),
            "AntiAfk-Script": (99_000_000, 100_000_000),
            "Items-Script": (199_000_000, 200_000_000)
        }
        
        for plan_name, (min_price, max_price) in plan_ranges.items():
            if min_price <= amount <= max_price:
                plan = plan_name
                if plan_name == "1d":
                    days = 1
                elif plan_name == "7d":
                    days = 7
                elif plan_name == "30d":
                    days = 30
                elif plan_name == "90d":
                    days = 90
                elif plan_name == "AntiAfk-Script":
                    days = "antiafk"
                elif plan_name == "Items-Script":
                    days = "items"
                break
        
        # Create the order
        orders[order_id] = {
            "discord_id": "unknown",  # Will be filled by admin verification
            "amount": amount,
            "days": days,
            "plan": plan,
            "status": "paid",
            "is_code_redemption": False,
            "created_at": datetime.now().isoformat(),
            "paid_at": datetime.now().isoformat(),
            "minecraft_username": data["minecraft_username"],
            "payment_details": data,
            "needs_verification": True  # Flag that this needs manual verification
        }
        
        save_orders(orders)
        
        print(f"💰 Direct payment recorded - Order: {order_id}, Player: {data['minecraft_username']}, Amount: {amount}, Plan: {plan}")
        
        # Send verification message to Discord (without Discord user mention)
        asyncio.run_coroutine_threadsafe(
            send_direct_payment_message(
                data['minecraft_username'],
                amount,
                plan,
                order_id
            ),
            bot.loop
        )
        
        return jsonify({
            "status": "success", 
            "order_id": order_id,
            "message": "Payment recorded, awaiting admin verification"
        })
        
    except Exception as e:
        print(f"❌ Direct payment failed: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

async def send_direct_payment_message(minecraft_username, amount, plan, order_id):
    """Send message for direct payments (without Discord user)"""
    try:
        channel = bot.get_channel(VERIFICATION_CHANNEL_ID)
        if not channel:
            print(f"Verification channel {VERIFICATION_CHANNEL_ID} not found")
            return None

        embed = discord.Embed(
            title="💰 Direct Payment Received",
            color=0x00FF00,
            description="**⚡ Direct payment detected! React with ✅ to verify and assign role**",
            timestamp=datetime.now(timezone.utc)
        )
        
        embed.add_field(name="Minecraft Username", value=f"```{minecraft_username}```", inline=True)
        embed.add_field(name="Amount", value=f"```{amount:,}```", inline=True)
        embed.add_field(name="Detected Plan", value=f"```{plan}```", inline=True)
        embed.add_field(name="Order ID", value=f"```{order_id}```", inline=False)
        embed.add_field(name="Status", value="🟡 **Needs Manual Verification**", inline=False)
        embed.add_field(name="Action Required", value="Please verify the payment and ask the user for their Discord ID to assign the role.", inline=False)
        
        message = await channel.send(embed=embed)
        await message.add_reaction("✅")
        
        print(f"✅ Direct payment message sent for order {order_id}")
        return message
        
    except Exception as e:
        print(f"Error sending direct payment message: {e}")
        return None

@flask_app.route('/redeem_code', methods=['POST'])
def redeem_code():
    try:
        data = request.get_json()
        print(f"📥 Received redeem_code request: {data}")
        
        if not data:
            return jsonify({"status": "error", "message": "No JSON data received"}), 400

        required = ['discord_id', 'code', 'plan', 'days']
        if not all(field in data for field in required):
            error_msg = f"Missing required fields: {required}"
            print(f"❌ {error_msg}")
            return jsonify({"status": "error", "message": error_msg}), 400

        codes_data = load_codes()
        code_data = next((c for c in codes_data["codes"] if c["code"] == data["code"] and not c.get("redeemed", False)), None)
        
        if not code_data:
            print(f"❌ Invalid code: {data['code']}")
            return jsonify({"status": "error", "message": "Invalid or already redeemed code"}), 400

        orders = load_orders()
        order_id = f"redeem_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        orders[order_id] = {
            "discord_id": data["discord_id"],
            "amount": 0,
            "days": data["days"],
            "plan": data["plan"],
            "status": "verified",
            "is_code_redemption": True,
            "created_at": datetime.now().isoformat(),
            "paid_at": datetime.now().isoformat(),
            "verified_at": datetime.now().isoformat(),
            "code_used": data["code"]
        }
        
        code_data.update({
            "redeemed": True,
            "redeemed_by": data["discord_id"],
            "redeemed_at": datetime.now().isoformat()
        })
        
        save_orders(orders)
        save_codes(codes_data)
        
        print(f"✅ Code redeemed: {data['code']} by {data['discord_id']}")
        return jsonify({"status": "success"})
    
    except Exception as e:
        print(f"❌ Code redemption failed: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ========== DISCORD COMMANDS ==========
@bot.tree.command(name="purchase", description="Purchase premium access")
async def purchase(interaction: discord.Interaction, plan: Literal["1d", "7d", "30d", "90d", "AntiAfk-Script", "Items-Script"]):
    try:
        await interaction.response.defer(ephemeral=True)
        
        plans = {
            "1d": {"price": random.randint(19_000_000, 20_000_000), "days": 1},
            "7d": {"price": random.randint(49_000_000, 50_000_000), "days": 7},
            "30d": {"price": random.randint(119_000_000, 120_000_000), "days": 30},
            "90d": {"price": random.randint(199_000_000, 200_000_000), "days": 90},
            "AntiAfk-Script": {"price": random.randint(99_000_000, 100_000_000), "days": "antiafk"},
            "Items-Script": {"price": random.randint(199_000_000, 200_000_000), "days": "items"}
        }
        
        amount = plans[plan]["price"]
        days = plans[plan]["days"]
        
        payload = {
            "discord_id": str(interaction.user.id),
            "amount": amount,
            "days": days,
            "plan": plan,
            "is_code_redemption": False
        }
        
        url = f"{API_URL}/create_order"
        print(f"📤 Purchase request to: {url}")
        print(f"📦 Payload: {payload}")
        
        headers = {'Content-Type': 'application/json'}
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            print(f"📥 Response status: {response.status_code}")
            
            if response.status_code != 200:
                # Fallback: create order locally
                print("🔄 Falling back to local order creation...")
                orders = load_orders()
                order_id = f"order_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                
                orders[order_id] = {
                    **payload,
                    "status": "pending",
                    "created_at": datetime.now().isoformat()
                }
                
                save_orders(orders)
                
                payment_message = (
                    f"💎 Инструкция по покупке:\n\n"
                    f"Отправьте `{amount:,}` игроку `{PAYMENT_TARGET}` на Анархии 602 (/an602)\n"
                    f"Команда: ```/pay {PAYMENT_TARGET} {amount}```\n\n"
                    f"После покупки ваш заказ передастся администрации!"
                )
                
                await interaction.followup.send(payment_message, ephemeral=True)
                return
                
            response_data = response.json()
            
            if response_data.get("status") != "success":
                error_msg = response_data.get('message', 'Unknown error')
                await interaction.followup.send(f"❌ Error: {error_msg}", ephemeral=True)
                return
            
            payment_message = (
                f"💎 Инструкция по покупке:\n\n"
                f"Отправьте `{amount:,}` игроку `{PAYMENT_TARGET}` на Анархии 602 (/an602)\n"
                f"Команда: ```/pay {PAYMENT_TARGET} {amount}```\n\n"
                f"После покупки ваш заказ передастся администрации!"
            )
            
            await interaction.followup.send(payment_message, ephemeral=True)
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Request error: {e}")
            # Fallback to local order creation
            orders = load_orders()
            order_id = f"order_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            orders[order_id] = {
                **payload,
                "status": "pending",
                "created_at": datetime.now().isoformat()
            }
            
            save_orders(orders)
            
            payment_message = (
                f"💎 Инструкция по покупке:\n\n"
                f"Отправьте `{amount:,}` игроку `{PAYMENT_TARGET}` на Анархии 602 (/an602)\n"
                f"Команда: ```/pay {PAYMENT_TARGET} {amount}```\n\n"
                f"После покупки ваш заказ передастся администрации!"
            )
            
            await interaction.followup.send(payment_message, ephemeral=True)
        
    except Exception as e:
        print(f"❌ Purchase command error: {type(e).__name__}: {e}")
        await interaction.followup.send("❌ Error processing purchase", ephemeral=True)

# [Include other commands: redeem, generate_codes, check_codes, on_raw_reaction_add, verify_order_from_reaction]

@bot.tree.command(name="redeem", description="Redeem a premium code")
async def redeem(interaction: discord.Interaction, code: str):
    try:
        await interaction.response.defer(ephemeral=True)
        
        with open(CODES_FILE, 'r') as f:
            data = json.load(f)
        
        code_data = next((c for c in data["codes"] if c["code"] == code and not c.get("redeemed", False)), None)
        
        if not code_data:
            await interaction.followup.send("❌ Invalid or already redeemed code!", ephemeral=True)
            return
            
        payload = {
            "discord_id": str(interaction.user.id),
            "code": code,
            "plan": code_data["plan"],
            "days": code_data["days"]
        }
        
        try:
            response = requests.post(f"{API_URL}/redeem_code", json=payload, timeout=30)
            if response.status_code != 200:
                raise Exception("API unavailable")
        except:
            # Local processing fallback
            codes_data = load_codes()
            code_data_local = next((c for c in codes_data["codes"] if c["code"] == code and not c.get("redeemed", False)), None)
            
            if not code_data_local:
                await interaction.followup.send("❌ Invalid or already redeemed code!", ephemeral=True)
                return

            orders = load_orders()
            order_id = f"redeem_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            orders[order_id] = {
                "discord_id": str(interaction.user.id),
                "amount": 0,
                "days": code_data_local["days"],
                "plan": code_data_local["plan"],
                "status": "verified",
                "is_code_redemption": True,
                "created_at": datetime.now().isoformat(),
                "paid_at": datetime.now().isoformat(),
                "verified_at": datetime.now().isoformat(),
                "code_used": code
            }
            
            code_data_local.update({
                "redeemed": True,
                "redeemed_by": str(interaction.user.id),
                "redeemed_at": datetime.now().isoformat()
            })
            
            save_orders(orders)
            save_codes(codes_data)
            
        code_data["redeemed"] = True
        code_data["redeemed_by"] = str(interaction.user.id)
        code_data["redeemed_at"] = datetime.utcnow().isoformat()
        
        with open(CODES_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        
        try:
            guild = bot.get_guild(GUILD_ID)
            if guild:
                member = guild.get_member(interaction.user.id)
                if member:
                    role = guild.get_role(PREMIUM_ROLE_ID)
                    if role:
                        await member.add_roles(role)
                        print(f"✅ Role assigned to {interaction.user.display_name} via code redemption")
        except Exception as e:
            print(f"Role assignment error: {e}")
        
        try:
            dm_message = (
                f"✅ Промокод успешно введен на {code_data['plan']}! Вы получили доступ к конфигурациям.\n\n"
                f"Если не загружается кфг - при входе в майн копируется хвид (если не копируется то используйте https://discord.com/channels/1288902708777979904/1424880610324910121)\n"
                f"В канале авторизации пиши `/register + хвид`\n"
                f"**ПРИМЕР КОМАНДЫ ДЛЯ АВТОРИЗАЦИИ:** `/register hwid: 731106141075386bfac06e0f2ab053be`\n"
                f"Канал находится в дискорд сервере невера. После авторизации перезапусти майн!"
            )
            dm_channel = await interaction.user.create_dm()
            await dm_channel.send(dm_message)
            print(f"✅ DM sent to {interaction.user.display_name} for code redemption")
        except discord.Forbidden:
            print(f"❌ Cannot send DM to {interaction.user.display_name} (DMs disabled)")
        except Exception as e:
            print(f"❌ Error sending DM for code redemption: {e}")
        
        await interaction.followup.send(
            f"✅ Промокод успешно введен на {code_data['plan']}! Вы получили доступ к конфигурациям.",
            ephemeral=True
        )
        
    except Exception as e:
        print(f"Redeem error: {e}")
        await interaction.followup.send("❌ Error redeeming code", ephemeral=True)

@bot.tree.command(name="generate_codes", description="[ADMIN] Generate premium codes")
async def generate_codes(
    interaction: discord.Interaction,
    plan: Literal["1d", "7d", "30d", "90d", "AntiAfk-Script", "Items-Script"],
    count: int = 1
):
    try:
        if not is_admin(interaction.user.id):
            await interaction.response.send_message("❌ No permission!", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
            
        plan_data = {
            "1d": {"days": 1}, "7d": {"days": 7}, "30d": {"days": 30}, "90d": {"days": 90},
            "AntiAfk-Script": {"days": "antiafk"}, "Items-Script": {"days": "items"}
        }
        
        with open(CODES_FILE, 'r') as f:
            data = json.load(f)
            
        new_codes = []
        for _ in range(min(count, 50)):
            code = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=10))
            new_code = {
                "code": code, 
                "plan": plan, 
                "days": plan_data[plan]["days"],
                "created_at": datetime.now(timezone.utc).isoformat(), 
                "created_by": str(interaction.user.id), 
                "redeemed": False
            }
            data["codes"].append(new_code)
            new_codes.append(f"`{code}` - {plan}")
            
        with open(CODES_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        
        codes_text = "\n".join(new_codes)
        if len(codes_text) > 2000:
            chunks = [codes_text[i:i+2000] for i in range(0, len(codes_text), 2000)]
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await interaction.followup.send(f"✅ Generated {len(new_codes)} {plan} codes:\n\n{chunk}", ephemeral=True)
                else:
                    await interaction.followup.send(chunk, ephemeral=True)
        else:
            await interaction.followup.send(f"✅ Generated {len(new_codes)} {plan} codes:\n\n{codes_text}", ephemeral=True)
        
    except Exception as e:
        print(f"Generate error: {e}")
        await interaction.followup.send("❌ Error generating codes", ephemeral=True)

@bot.tree.command(name="check_codes", description="[ADMIN] Check available codes")
async def check_codes(interaction: discord.Interaction):
    try:
        if not is_admin(interaction.user.id):
            await interaction.response.send_message("❌ No permission!", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
            
        with open(CODES_FILE, 'r') as f:
            data = json.load(f)
            
        available_codes = [c for c in data["codes"] if not c["redeemed"]]
        
        if not available_codes:
            await interaction.followup.send("ℹ️ No available codes", ephemeral=True)
            return
            
        message = ["**Available codes:**"]
        for code in available_codes:
            created_at = datetime.fromisoformat(code["created_at"].replace('Z', '+00:00')).strftime("%Y-%m-%d %H:%M")
            message.append(
                f"`{code['code']}` - {code['plan']} (Created by <@{code['created_by']}> on {created_at})"
            )
        
        full_message = "\n".join(message)
        if len(full_message) > 2000:
            chunks = [full_message[i:i+2000] for i in range(0, len(full_message), 2000)]
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await interaction.followup.send(chunk, ephemeral=True)
                else:
                    await interaction.followup.send(chunk, ephemeral=True)
        else:
            await interaction.followup.send(full_message, ephemeral=True)
        
    except Exception as e:
        print(f"Check codes error: {e}")
        await interaction.followup.send("❌ Error checking codes", ephemeral=True)

@bot.event
async def on_raw_reaction_add(payload):
    """Handle reaction verification"""
    try:
        if payload.channel_id != VERIFICATION_CHANNEL_ID:
            return
            
        if str(payload.emoji) != "✅":
            return
            
        if not is_admin(payload.user_id):
            return
            
        channel = bot.get_channel(payload.channel_id)
        if not channel:
            return
            
        message = await channel.fetch_message(payload.message_id)
        
        if not message.embeds:
            return
            
        embed = message.embeds[0]
        
        # Handle both regular and direct payment embeds
        is_payment_embed = ("Payment Verification Required" in embed.title or 
                           "Direct Payment Received" in embed.title)
        
        if not is_payment_embed:
            return
        
        order_id = None
        for field in embed.fields:
            if field.name == "Order ID":
                order_id = field.value.strip('`')
                break
        
        if not order_id:
            return
        
        await verify_order_from_reaction(order_id, payload.user_id, message)
        
    except Exception as e:
        print(f"Reaction verification error: {e}")

async def verify_order_from_reaction(order_id, admin_id, message):
    """Verify order when admin reacts with ✅"""
    try:
        embed = message.embeds[0]
        discord_id = None
        minecraft_username = None
        plan = None
        amount = None
        
        for field in embed.fields:
            if field.name == "Discord User":
                discord_id = field.value.replace('<@', '').replace('>', '').strip()
            elif field.name == "Minecraft Username":
                minecraft_username = field.value.strip('`')
            elif field.name == "Plan":
                plan = field.value.strip('`')
            elif field.name == "Amount":
                amount = field.value.strip('`').replace(',', '')
        
        # Update order status
        orders = load_orders()
        if order_id in orders:
            orders[order_id]["status"] = "verified"
            orders[order_id]["verified_at"] = datetime.now().isoformat()
            orders[order_id]["verified_by"] = str(admin_id)
            
            # If this was a direct payment, we might not have a Discord ID yet
            if not discord_id and "discord_id" in orders[order_id] and orders[order_id]["discord_id"] != "unknown":
                discord_id = orders[order_id]["discord_id"]
            
            save_orders(orders)
        
        # Assign role if we have Discord ID
        if discord_id and discord_id != "unknown":
            guild = bot.get_guild(GUILD_ID)
            if guild:
                member = guild.get_member(int(discord_id))
                if member:
                    role = guild.get_role(PREMIUM_ROLE_ID)
                    if role:
                        await member.add_roles(role)
                        print(f"✅ Role {PREMIUM_ROLE_ID} assigned to {member.display_name}")
                        
                        try:
                            admin_user = await bot.fetch_user(admin_id)
                            dm_message = (
                                f"🎉 Ваша покупка подтверждена! Вы получили доступ к конфигурациям.\n\n"
                                f"**Детали заказа:**\n"
                                f"• План: {plan}\n"
                                f"• Сумма: {int(amount):,}\n"
                                f"• Подтверждено: {admin_user.display_name}\n\n"
                                f"Если не загружается кфг - при входе в майн копируется хвид (если не копируется то используйте https://discord.com/channels/1288902708777979904/1424880610324910121)\n"
                                f"В канале авторизации пиши `/register + хвид`\n"
                                f"**ПРИМЕР КОМАНДЫ ДЛЯ АВТОРИЗАЦИИ:** `/register hwid: 731106141075386bfac06e0f2ab053be`\n"
                                f"Канал находится в дискорд сервере невера. После авторизации перезапусти майн!"
                            )
                            
                            dm_channel = await member.create_dm()
                            await dm_channel.send(dm_message)
                            print(f"✅ DM sent to {member.display_name}")
                            
                        except discord.Forbidden:
                            print(f"❌ Cannot send DM to {member.display_name} (DMs disabled)")
                        except Exception as e:
                            print(f"❌ Error sending DM: {e}")
        
        embed.title = "✅ Payment Verified"
        embed.color = discord.Color.green()
        embed.add_field(name="✅ Verified By", value=f"<@{admin_id}>", inline=True)
        embed.add_field(name="🕒 Verified At", value=f"<t:{int(datetime.now(timezone.utc).timestamp())}:R>", inline=True)
        
        await message.edit(embed=embed)
        await message.clear_reactions()
        
        print(f"Order {order_id} verified by {admin_id}")
        
    except Exception as e:
        print(f"Order verification error: {e}")

@bot.event
async def on_ready():
    print(f"✅ Discord bot logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} commands")
        print(f"🌐 API Server URL: {API_URL}")
        
        # Test the API endpoint
        try:
            response = requests.get(f"{API_URL}/health", timeout=10)
            print(f"🌐 API Health check: {response.status_code}")
        except:
            print("⚠️  API health check failed - running in fallback mode")
        
    except Exception as e:
        print(f"❌ Sync error: {e}")

# ========== START BOTH SERVERS ==========
def run_flask():
    port = int(os.getenv('PORT', 5000))
    print(f"🚀 Starting Flask server on port {port}")
    
    # Use production server
    from waitress import serve
    serve(flask_app, host='0.0.0.0', port=port, threads=4)

if __name__ == "__main__":
    print("🚀 Starting combined Discord bot and API server...")
    
    if not DISCORD_BOT_TOKEN:
        print("❌ DISCORD_BOT_TOKEN environment variable is required!")
        exit(1)
    
    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("✅ Flask API server started")
    
    # Start Discord bot in the main thread
    print("✅ Starting Discord bot...")
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except Exception as e:
        print(f"❌ Discord bot failed: {e}")

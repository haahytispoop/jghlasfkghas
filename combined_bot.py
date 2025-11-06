import os
import discord
from discord.ext import commands
import random
import json
from typing import Literal
from datetime import datetime, timezone
import asyncio

print("🚀 Starting Discord bot with built-in payment processing...")

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

# Initialize Discord bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True
bot = commands.Bot(command_prefix="!", intents=intents)

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

async def send_verification_message(discord_id, amount, plan, minecraft_username=None, order_id=None):
    """Send verification message to admin channel"""
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
            description="**⚡ Direct payment detected! React with ✅ to verify**",
            timestamp=datetime.now(timezone.utc)
        )
        
        embed.add_field(name="Minecraft Username", value=f"```{minecraft_username}```", inline=True)
        embed.add_field(name="Amount", value=f"```{amount:,}```", inline=True)
        embed.add_field(name="Detected Plan", value=f"```{plan}```", inline=True)
        embed.add_field(name="Order ID", value=f"```{order_id}```", inline=False)
        embed.add_field(name="Status", value="🟡 **Needs Manual Verification**", inline=False)
        embed.add_field(name="Action", value="Ask user for Discord ID and use `/manual_verify` command", inline=False)
        
        message = await channel.send(embed=embed)
        await message.add_reaction("✅")
        
        print(f"✅ Direct payment message sent for order {order_id}")
        return message
        
    except Exception as e:
        print(f"Error sending direct payment message: {e}")
        return None

def process_direct_payment(minecraft_username, amount):
    """Process direct payment from Minecraft (called via HTTP or internally)"""
    try:
        print(f"💰 Processing direct payment: {amount} from {minecraft_username}")
        
        # Try to find which plan this amount corresponds to
        plan_ranges = {
            "1d": (19_000_000, 20_000_000),
            "7d": (49_000_000, 50_000_000), 
            "30d": (119_000_000, 120_000_000),
            "90d": (199_000_000, 200_000_000),
            "AntiAfk-Script": (99_000_000, 100_000_000),
            "Items-Script": (199_000_000, 200_000_000)
        }
        
        plan = "Unknown"
        days = 1
        
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
        orders = load_orders()
        order_id = f"direct_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        orders[order_id] = {
            "discord_id": "unknown",
            "amount": amount,
            "days": days,
            "plan": plan,
            "status": "paid",
            "is_code_redemption": False,
            "created_at": datetime.now().isoformat(),
            "paid_at": datetime.now().isoformat(),
            "minecraft_username": minecraft_username,
            "needs_verification": True
        }
        
        save_orders(orders)
        
        print(f"💰 Direct payment recorded - Order: {order_id}, Player: {minecraft_username}, Amount: {amount}, Plan: {plan}")
        
        # Send verification message to Discord
        asyncio.create_task(send_direct_payment_message(minecraft_username, amount, plan, order_id))
        
        return {
            "status": "success", 
            "order_id": order_id,
            "plan": plan,
            "message": "Payment recorded, awaiting admin verification"
        }
        
    except Exception as e:
        print(f"❌ Direct payment processing failed: {str(e)}")
        return {"status": "error", "message": str(e)}

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
        
        # Create order directly
        orders = load_orders()
        order_id = f"order_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        orders[order_id] = {
            "discord_id": str(interaction.user.id),
            "amount": amount,
            "days": days,
            "plan": plan,
            "status": "pending",
            "is_code_redemption": False,
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

@bot.tree.command(name="manual_verify", description="[ADMIN] Manually verify a direct payment")
async def manual_verify(interaction: discord.Interaction, order_id: str, discord_id: str):
    try:
        if not is_admin(interaction.user.id):
            await interaction.response.send_message("❌ No permission!", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        orders = load_orders()
        
        if order_id not in orders:
            await interaction.followup.send("❌ Order not found!", ephemeral=True)
            return
            
        order = orders[order_id]
        
        if order.get("status") == "verified":
            await interaction.followup.send("❌ Order already verified!", ephemeral=True)
            return
        
        # Update order with Discord ID
        orders[order_id]["discord_id"] = discord_id
        orders[order_id]["status"] = "verified"
        orders[order_id]["verified_at"] = datetime.now().isoformat()
        orders[order_id]["verified_by"] = str(interaction.user.id)
        
        save_orders(orders)
        
        # Assign role
        guild = bot.get_guild(GUILD_ID)
        if guild:
            member = guild.get_member(int(discord_id))
            if member:
                role = guild.get_role(PREMIUM_ROLE_ID)
                if role:
                    await member.add_roles(role)
                    print(f"✅ Role {PREMIUM_ROLE_ID} assigned to {member.display_name}")
                    
                    try:
                        dm_message = (
                            f"🎉 Ваша покупка подтверждена! Вы получили доступ к конфигурациям.\n\n"
                            f"**Детали заказа:**\n"
                            f"• План: {order['plan']}\n"
                            f"• Сумма: {order['amount']:,}\n"
                            f"• Подтверждено: {interaction.user.display_name}\n\n"
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
        
        await interaction.followup.send(f"✅ Order {order_id} verified! Role assigned to <@{discord_id}>", ephemeral=True)
        
    except Exception as e:
        print(f"Manual verify error: {e}")
        await interaction.followup.send("❌ Error verifying order", ephemeral=True)

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
            
        # Process code redemption locally
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
        
        # Update original data for response
        code_data["redeemed"] = True
        code_data["redeemed_by"] = str(interaction.user.id)
        code_data["redeemed_at"] = datetime.utcnow().isoformat()
        
        with open(CODES_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        
        # Assign role
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
        
        # Send DM
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
        
    except Exception as e:
        print(f"❌ Sync error: {e}")

# Simple HTTP server for Minecraft payments
import http.server
import socketserver
import threading

class PaymentHandler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/direct_payment':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data.decode('utf-8'))
                minecraft_username = data.get('minecraft_username')
                amount = data.get('amount')
                
                if minecraft_username and amount:
                    result = process_direct_payment(minecraft_username, amount)
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps(result).encode('utf-8'))
                else:
                    self.send_response(400)
                    self.end_headers()
                    
            except Exception as e:
                print(f"HTTP payment error: {e}")
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

def run_http_server():
    PORT = 8080
    with socketserver.TCPServer(("", PORT), PaymentHandler) as httpd:
        print(f"🌐 HTTP payment server running on port {PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    print("🚀 Starting Discord bot with HTTP payment server...")
    
    if not DISCORD_BOT_TOKEN:
        print("❌ DISCORD_BOT_TOKEN environment variable is required!")
        exit(1)
    
    # Start HTTP server in a separate thread
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()
    print("✅ HTTP payment server started on port 8080")
    
    # Start Discord bot in the main thread
    print("✅ Starting Discord bot...")
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except Exception as e:
        print(f"❌ Discord bot failed: {e}")

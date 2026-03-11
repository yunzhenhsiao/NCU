import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from supabase import create_client, Client
from keep_alive import keep_alive
import time

keep_alive()
load_dotenv()

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url, key)

TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID_STR = int(os.getenv('GUILD_ID'))

class Client(commands.Bot):
    async def on_ready(self):
        print(f'Logged in as {self.user}')

        try:
            guild=discord.Object(id=GUILD_ID_STR)
            synced = await self.tree.sync(guild=guild)
            print(f'Synced {len(synced)} commands to guild {guild.id}.')
        except Exception as e:
            print(f'Error syncing commands: {e}')

    async def on_message(self, message):
        if message.author == self.user:
            return

        if message.content.startswith('!hello'):
            await message.channel.send(f'Hello, {message.author.mention}!')

    async def on_member_join(self, member):
        channel = member.guild.system_channel
        if channel is not None:
            await channel.send(f'歡迎 {member.mention} 加入伺服器!' + '詳細功能請打"/"查看操作手冊')

class View(discord.ui.View):
    def __init__(self, host: discord.Member):
        super().__init__()
        self.host = host  # 在初始化時記住這台車的主揪是誰

    @discord.ui.button(label="加入拼車", style=discord.ButtonStyle.primary)
    async def join_ride(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 1. 檢查加入者是不是就是主揪本人（選擇性）
        if interaction.user.id == self.host.id:
            await interaction.response.send_message("你不能加入自己開的車喔！", ephemeral=True)
            return

        # 2. 呼叫建立討論串的函數
        # 先回覆「處理中」，避免互動逾時
        await interaction.response.defer(ephemeral=True) 
        
        await self.create_carpool_thread(interaction, self.host)

    async def create_carpool_thread(self, interaction: discord.Interaction, host: discord.Member):
        # 1. 取得當前的頻道
        channel = interaction.channel 
        
        # 2. 建立私密討論串
        thread = await channel.create_thread(
            name=f"🚗 拼車確認：{interaction.user.name} 與 {host.name}",
            type=discord.ChannelType.private_thread,
            invitable=False
        )
        
        # 3. 把主揪和加入者拉進討論串
        await thread.add_user(host)
        await thread.add_user(interaction.user)
        
        # 4. 在討論串發送第一則訊息
        await thread.send(f"✅ 哈囉 {host.mention} 和 {interaction.user.mention}！你們可以在這裡確認拼車細節。")
        
        # 5. 使用 followup 回覆原本的按鈕（因為前面用了 defer）
        await interaction.followup.send(f"已建立私密討論串：{thread.mention}", ephemeral=True)

class CarpoolSelect(discord.ui.Select):
    def __init__(self, options, rides_data):
        # options 是顯示在選單上的選項
        # rides_data 是為了讓我們能根據選中的 ID 找回主揪資訊
        super().__init__(placeholder="選擇你想加入的拼車...", options=options)
        self.rides_data = rides_data

    async def callback(self, interaction: discord.Interaction):
        # 使用者選中某個選項後會執行這裡
        selected_ride_id = self.values[0]
        
        # 從 rides_data 找出該筆資料
        ride = next((r for r in self.rides_data if r["id"] == selected_ride_id), None)
        
        if not ride:
            await interaction.response.send_message("找不到該車次資訊，請重新查詢。", ephemeral=True)
            return

        if str(interaction.user.id) == ride["host_id"]:
            await interaction.response.send_message("❌ 你不能加入自己開的車喔！", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)

        # 取得主揪成員物件
        guild = interaction.guild
        host_id = int(ride["host_id"])
        try:
            host = guild.get_member(host_id) or await guild.fetch_member(host_id)
        except:
            await interaction.followup.send("無法聯繫上主揪，請稍後再試。", ephemeral=True)
            return

        # 呼叫建立討論串的邏輯 (我們可以把這段邏輯抽出來)
        await self.create_thread_logic(interaction, host)

    async def create_thread_logic(self, interaction: discord.Interaction, host: discord.Member):
        thread = await interaction.channel.create_thread(
            name=f"🚗 拼車確認：{interaction.user.name} 與 {host.name}",
            type=discord.ChannelType.private_thread,
            invitable=False
        )
        await thread.add_user(host)
        await thread.add_user(interaction.user)
        await thread.send(f"✅ {host.mention}，{interaction.user.mention} 透過下拉選單申請加入您的拼車！")
        await interaction.followup.send(f"已建立私密討論串：{thread.mention}", ephemeral=True)

class CarpoolView(discord.ui.View):
    def __init__(self, options, rides_data):
        super().__init__()
        # 將下拉選單加入 View 中
        self.add_item(CarpoolSelect(options, rides_data))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = Client(command_prefix='!', intents=intents)

GUILD_ID = discord.Object(id=GUILD_ID_STR)  # 替換為你的伺服器ID

@client.tree.command(name='操作手冊', description='顯示操作手冊', guild=GUILD_ID)
async def help(interaction: discord.Interaction):
    embed=discord.Embed(title="操作手冊", description=" ", color=discord.Color.blue())
    embed.add_field(name="查詢拼車", value="--輸入篩選條件(目的地) 僅限該使用者能看到結果", inline=False)
    embed.add_field(name="新增拼車", value="--請輸入拼車詳細資訊:\n出發地/目的地/出發時間/乘客數量/備註(可不填)", inline=False)
    await interaction.response.send_message(embed=embed)

# @client.tree.command(name='查詢拼車', description='輸入篩選條件 僅限該使用者能看到結果', guild=GUILD_ID)
# async def carCards(interaction: discord.Interaction, filter: str): #叫Dify解析篩選條件(傳入的filter) 到資料庫過濾後傳回符合條件的card
#     host_example = interaction.user 
#     content = f'以下是符合條件：{filter}的拼車資訊'
#     await interaction.response.send_message(content, view=View(host=host_example), ephemeral=True)

@client.tree.command(name='查詢拼車', description='請輸入要查詢的目的地', guild=GUILD_ID)
async def carCards(interaction: discord.Interaction, destination: str):
    await interaction.response.defer(ephemeral=True)

    # 從 Supabase 搜尋目的地相符且狀態為 active 的車
    response = supabase.table("carpool_rides") \
        .select("*") \
        .eq("destination", destination) \
        .eq("status", "active") \
        .execute()

    rides = response.data

    if not rides:
        await interaction.followup.send(f"目前沒有去 {destination} 的車次喔！", ephemeral=True)
        return

    embeds_list = []
    select_options = []

    for ride in rides:
        host_id = int(ride["host_id"])
        guild = interaction.guild
        host_member = guild.get_member(host_id) 
        display_name = host_member.display_name if host_member else f"使用者({host_id})"

        # 建立 Embed
        embed = discord.Embed(title=f"🚗 往 {ride['destination']}", color=discord.Color.blue())
        embed.add_field(name="時間", value=ride["ride_time"], inline=True)
        embed.add_field(name="主揪", value=display_name, inline=True)
        embeds_list.append(embed)

        # 建立下拉選單的選項
        # label: 使用者看到的文字, value: 程式處理用的 ID
        select_options.append(discord.SelectOption(
            label=f"往 {destination} ({ride['ride_time']})",
            description=f"主揪：{display_name}，乘客數量：{ride['passenger']}",
            value=ride["id"]
        ))

    # 發送訊息，帶入 embeds 和包含選單的 view
    await interaction.followup.send(
        content="請選擇想加入的車次：",
        embeds=embeds_list,
        view=CarpoolView(select_options, rides),
        ephemeral=True
    )

@client.tree.command(name='新增拼車', description='請輸入拼車詳細資訊', guild=GUILD_ID)
async def createRide(interaction: discord.Interaction, content: str):
    await interaction.response.defer() # 因為連資料庫需要時間，先 defer
    
    host = interaction.user
    content_parts = content.split(' ')
    departure = content_parts[0] if len(content_parts) > 0 else await interaction.followup.send("未知出發地", ephemeral=True)
    destination = content_parts[1] if len(content_parts) > 1 else await interaction.followup.send("未知目的地", ephemeral=True)
    ride_time = content_parts[2] if len(content_parts) > 2 else await interaction.followup.send("未知時間", ephemeral=True)
    passenger = content_parts[3] if len(content_parts) > 3 else await interaction.followup.send("未知人數", ephemeral=True)
    notes = ' '.join(content_parts[4:]) if len(content_parts) > 4 else "無備註"

    data = {
        "host_id": str(host.id),
        "departure": departure,
        "destination": destination, 
        "ride_time": ride_time,
        "passenger": passenger,
        "notes": notes,
        "status": "active"
    }

    try:
        # 寫入 Supabase
        response = supabase.table("carpool_rides").insert(data).execute()
        
        await interaction.followup.send(
            f'✅ 成功發布拼車！\n主揪：{host.mention}\n出發地：{departure}\n目的地：{destination}\n時間：{ride_time}\n人數：{passenger}\n備註：{notes}', 
            view=View(host=host)
        )
    except Exception as e:
        print(f"DB Error: {e}")
        await interaction.followup.send("資料庫存取失敗，請稍後再試。")

@client.tree.command(name='清除對話', description='刪除此頻道的所有對話（測試用）', guild=GUILD_ID)
@app_commands.checks.has_permissions(manage_messages=True) # 確保只有管理員或特定權限者能用
async def purge(interaction: discord.Interaction, limit: int = 100):
    deleted = await interaction.channel.purge(limit=limit)
    await interaction.followup.send(f"✅ 清理完成！已刪除 {len(deleted)} 則訊息。", ephemeral=True)
if __name__ == "__main__":
    keep_alive()
    time.sleep(5)  # 稍微延遲，避開頻繁連線
    client.run(TOKEN)

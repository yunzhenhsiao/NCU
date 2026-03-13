import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from supabase import create_client, Client
from keep_alive import keep_alive
import time
from datetime import timedelta, timezone, datetime
from discord.ext import tasks
import asyncio

keep_alive()
load_dotenv()

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url, key)

TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID_STR = int(os.getenv('GUILD_ID'))
MAIN_CHANNEL_ID = int(os.getenv('MAIN_CHANNEL_ID'))
GUILD_ID = discord.Object(id=GUILD_ID_STR)  # 替換為你的伺服器ID
tz_tw = timezone(timedelta(hours=8))


# 定義 Bot
class Client(commands.Bot):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    # 定時任務：每 10 分鐘檢查一次，看看有哪些車即將發車（10 分鐘內），然後發送提醒並關閉按鈕
    @tasks.loop(minutes=10)
    async def check_rides_and_remind(self):
        now = datetime.now(tz_tw)
        # 提醒閾值：現在時間 + 10 分鐘
        threshold = now + timedelta(minutes=10)

        # 1. 撈出符合條件的車：active、尚未發過提醒
        # 我們不限定「剛好」10分鐘，而是「小於等於 10 分鐘」的所有歷史未發送車次
        response = supabase.table("rides")\
            .select("*")\
            .eq("status", "active")\
            .eq("reminder_sent", False)\
            .execute()

        for ride in response.data:
            # 合併日期時間並掛上台北時區
            ride_dt_str = f"{ride['ride_date']} {ride['ride_time']}"
            ride_dt = datetime.strptime(ride_dt_str, "%Y-%m-%d %H:%M").replace(tzinfo=tz_tw)

            if ride_dt <= threshold:
                # --- 執行提醒與關閉邏輯 ---
                
                # A. 更新資料庫狀態（先更新資料庫，防止程式當掉重複發送）
                supabase.table("rides").update({
                    "status": "inactive",
                    "reminder_sent": True
                }).eq("id", ride['id']).execute()

                # B. 關閉原訊息的按鈕
                try:
                    channel = self.get_channel(int(ride['channel_id']))
                    if channel:
                        msg = await channel.fetch_message(int(ride['message_id']))
                        # 修改 Embed 顏色或內容，並移除 view (按鈕)
                        embed = msg.embeds[0]
                        embed.color = discord.Color.red()
                        embed.title = "🔒 拼車招募已結束"
                        await msg.edit(content="🔔 **本車已發車或停止招募**", embed=embed, view=None)
                except Exception as e:
                    print(f"修改訊息失敗 (可能訊息已被刪除): {e}")

                # C. 發送提醒到私人討論串
                try:
                    thread = await self.fetch_channel(int(ride['thread_id']))
                    if thread:
                        await thread.send(f"⚠️ **發車提醒**：各位乘客好，本車將於 10 分鐘內發車！請準備前往集合地點。")
                        await thread.send("*(本討論串已自動關閉加入功能)*")
                except Exception as e:
                    print(f"討論串發送提醒失敗: {e}")
                
                # 避免連續修改訊息太快，小睡一下
                await asyncio.sleep(1)

    # 定時任務：每週檢查一次，看看有哪些車已經過期（發車時間在現在之前），然後標記為刪除並關閉討論串
    @tasks.loop(hours=168) # 168 小時 = 7 天
    async def weekly_cleanup(self):
        now = datetime.now(tz_tw)
        
        # 撈出所有已經發車（過去時間）且尚未歸檔的車
        # 為了簡單起見，這裡先撈出 status 為 inactive 且 is_deleted 為 False 的
        response = supabase.table("rides")\
            .select("*")\
            .eq("is_deleted", False)\
            .execute()

        for ride in response.data:
            ride_dt_str = f"{ride['ride_date']} {ride['ride_time']}"
            ride_dt = datetime.strptime(ride_dt_str, "%Y-%m-%d %H:%M").replace(tzinfo=tz_tw)

            if ride_dt < now:
                # 執行歸檔：標記 is_deleted
                supabase.table("rides").update({"is_deleted": True}).eq("id", ride['id']).execute()
                
                # 關閉/歸檔討論串 (避免討論串列表太亂)
                try:
                    thread = await self.fetch_channel(int(ride['thread_id']))
                    if thread:
                        await thread.edit(archived=True, locked=True)
                except Exception as e:
                    print(f"歸檔討論串失敗: {e}")

                # 遵守你的 Rate Limit 建議，處理大量資料時每筆休息 1 秒
                await asyncio.sleep(1)
                
    async def on_ready(self):
        print(f'Logged in as {self.user}')

        # 1. 啟動排程任務
        if not self.check_rides_and_remind.is_running():
            self.check_rides_and_remind.start()
        if not self.weekly_cleanup.is_running():
            self.weekly_cleanup.start()

        # 2. 核心修正：自動恢復所有 Active 車次的按鈕監聽
        print("正在恢復拼車按鈕監聽...")
        try:
            # 撈出所有狀態為 active 的車次
            active_rides = supabase.table("rides")\
                .select("id", "host_id")\
                .eq("status", "active")\
                .execute()
            
            count = 0
            for r in active_rides.data:
                # 重新註冊 View
                # 這裡的 RideActionView 必須傳入對應的 ride_id 和 host_id
                self.add_view(RideActionView(ride_id=r['id'], host_id=int(r['host_id'])))
                count += 1
            print(f"成功恢復 {count} 個拼車按鈕。")
        except Exception as e:
            print(f"恢復按鈕時發生錯誤: {e}")
        
        try:
            synced = await self.tree.sync(guild=GUILD_ID)
            print(f'Synced {len(synced)} commands.')
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
            await channel.send(f' {member.mention} 您好!' + '查看詳細功能請打"/"點選操作手冊')

# 定義一個 View，裡面有一個按鈕，按下去會建立私密討論串
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

# 下拉選單 繼承自 discord.ui.Select
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

# 包裹下拉選單的View
class CarpoolView(discord.ui.View):
    def __init__(self, options, rides_data):
        super().__init__()
        # 將下拉選單加入 View 中
        self.add_item(CarpoolSelect(options, rides_data))

# 這個 View 是在使用者成功建立拼車後，附加在公告訊息上的按鈕
class RideActionView(discord.ui.View):
    def __init__(self, ride_id: str, host_id: int):
        super().__init__(timeout=None)
        self.ride_id = ride_id
        self.host_id = host_id
        
        # 使用固定的 custom_id，機器人重啟後才能透過這個 ID 認出它
        self.add_item(discord.ui.Button(
            label="加入拼車", 
            style=discord.ButtonStyle.success, 
            custom_id=f"join:{ride_id}"
        ))
        self.add_item(discord.ui.Button(
            label="退出拼車", 
            style=discord.ButtonStyle.danger, 
            custom_id=f"leave:{ride_id}"
        ))

    # 針對動態 custom_id 的處理方式
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        cid = interaction.data.get('custom_id', '')
        if cid.startswith("join:"):
            if interaction.user.id == self.host_id:
                return await interaction.response.send_message("❌ 你是主揪，不能重複加入自己的車！", ephemeral=True)
            
            await interaction.response.defer(ephemeral=True)
            # 使用 self.ride_id 進行 RPC 呼叫
            res = supabase.rpc('join_ride', {'ride_uuid': self.ride_id, 'member_id': str(interaction.user.id)}).execute()
            if res.data['success']:
                # 取得最新資料來更新 UI
                ride = supabase.table("rides").select("*").eq("id", self.ride_id).single().execute().data
                
                # 通知討論串
                thread = await interaction.guild.fetch_channel(int(ride['thread_id']))
                await thread.add_user(interaction.user)
                await thread.send(f"✅ **{interaction.user.display_name}** 已加入拼車！目前人數：{ride['current_passengers']}/{ride['max_passengers']}")

                # 更新原訊息 Embed
                embed = interaction.message.embeds[0]
                embed.set_field_at(2, name="👥 人數", value=f"{ride['current_passengers']} / {ride['max_passengers']}", inline=True)
                
                # 檢查是否滿人需要關閉按鈕
                if ride['current_passengers'] >= ride['max_passengers']:
                    await interaction.message.edit(content="🔒 **本車已滿員**", embed=embed, view=None)
                    supabase.table("rides").update({"status": "inactive"}).eq("id", self.ride_id).execute()
                else:
                    await interaction.message.edit(embed=embed)

                await interaction.followup.send("成功加入！", ephemeral=True)
            else:
                await interaction.followup.send(f"無法加入：{res.data['message']}", ephemeral=True)
            pass
        elif cid.startswith("leave:"):
            if interaction.user.id == self.host_id:
                return await interaction.response.send_message("❌ 主揪不能退出，請直接使用「刪除拼車」功能。", ephemeral=True)
            await interaction.response.defer(ephemeral=True)
            
            # 呼叫 RPC 退出
            res = supabase.rpc('leave_ride', {'ride_uuid': self.ride_id, 'member_id': str(interaction.user.id)}).execute()

            if res.data['success']:
                ride = supabase.table("rides").select("*").eq("id", self.ride_id).single().execute().data
                
                # 從討論串移除並通知
                thread = await interaction.guild.fetch_channel(int(ride['thread_id']))
                await thread.remove_user(interaction.user)
                await thread.send(f"👋 **{interaction.user.display_name}** 已退出拼車，目前剩餘 {ride['max_passengers'] - ride['current_passengers']} 個空位！")

                # 恢復原訊息的「可加入」狀態與按鈕
                embed = interaction.message.embeds[0]
                embed.set_field_at(2, name="👥 人數", value=f"{ride['current_passengers']} / {ride['max_passengers']}", inline=True)
                
                # 重新把 View 加回去 (如果之前因為滿員被移除了)
                await interaction.message.edit(content=f"{interaction.guild.get_member(self.host_id).mention} 發起了拼車！", embed=embed, view=self)

                await interaction.followup.send("已成功退出拼車。", ephemeral=True)
            else:
                await interaction.followup.send(f"失敗：{res.data['message']}", ephemeral=True)

            # (這是在 RideActionView 的 leave_btn 邏輯中)
            now = datetime.now(tz_tw)
            ride_dt = datetime.strptime(f"{ride['ride_date']} {ride['ride_time']}", "%Y-%m-%d %H:%M").replace(tzinfo=tz_tw)

            # 如果還沒到提醒時間 (剩餘時間 > 10 分鐘)
            if ride_dt > now + timedelta(minutes=10):
                # 1. 狀態改回 active，reminder_sent 改回 False (確保排程任務未來會再次抓到它)
                supabase.table("rides").update({
                    "status": "active",
                    "reminder_sent": False
                }).eq("id", self.ride_id).execute()
                
                # 2. 修改原訊息，把按鈕 (self) 重新塞進去
                msg = await interaction.channel.fetch_message(int(ride['message_id']))
                await msg.edit(content=f"{interaction.guild.get_member(self.host_id).mention} 發起了拼車！", view=self)
            pass
        return True
    

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = Client(command_prefix='!', intents=intents)


# 操作手冊
@client.tree.command(name='操作手冊', description='顯示操作手冊', guild=GUILD_ID)
async def help(interaction: discord.Interaction):
    if interaction.channel_id != MAIN_CHANNEL_ID:
        await interaction.response.send_message(
            f"❌ 本功能僅限在 <#{MAIN_CHANNEL_ID}> 頻道使用喔！", 
            ephemeral=True
        )
        return
    embed=discord.Embed(title="操作手冊", description=" ", color=discord.Color.blue())
    embed.add_field(name="查詢拼車", value="--輸入篩選條件(目的地) 僅限該使用者能看到結果", inline=False)
    embed.add_field(name="新增拼車", value="--請輸入拼車詳細資訊:\n出發地/目的地/出發時間/乘客數量/備註(可不填)", inline=False)
    await interaction.response.send_message(embed=embed)

# 查詢拼車
@client.tree.command(name='查詢拼車', description='請輸入要查詢的目的地', guild=GUILD_ID)
async def carCards(interaction: discord.Interaction, destination: str):
    if interaction.channel_id != MAIN_CHANNEL_ID:
        await interaction.response.send_message(
            f"❌ 本功能僅限在 <#{MAIN_CHANNEL_ID}> 頻道使用喔！", 
            ephemeral=True
        )
        return

    response = supabase.table("rides") \
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
# 新增拼車
@client.tree.command(name='新增拼車', description='請輸入拼車詳細資訊', guild=GUILD_ID)
@app_commands.describe(
    departure="出發地 (例如：校門口)",
    destination="目的地 (例如：桃園高鐵)",
    ride_date="日期 (格式：YYYY-MM-DD，例如 2026-03-20)",
    ride_time="時間 (建議以10分鐘為單位，例如 14:10)",
    passenger="乘客數量 (例如 3)",
    max_passengers="總人數 (包含主揪，預設4人)",
    notes="備註 (可不填)"
)
async def createRide(
    interaction: discord.Interaction, 
    departure: str, 
    destination: str, 
    ride_date: str, 
    ride_time: str, 
    passenger: int,
    max_passengers: int = 4, 
    notes: str = "無"
):
    # 1. 頻道鎖定：只能在指定頻道使用
    if interaction.channel_id != MAIN_CHANNEL_ID:
        await interaction.response.send_message(
            f"❌ 請至 <#{MAIN_CHANNEL_ID}> 頻道使用此指令！", ephemeral=True
        )
        return

    await interaction.response.defer() # 進入資料庫查詢流程

    host_id = str(interaction.user.id)

    # 2. 檢查是否已經有一台 active 的車
    existing_ride = supabase.table("rides")\
        .select("*")\
        .eq("host_id", host_id)\
        .eq("status", "active")\
        .execute()

    if existing_ride.data:
        await interaction.followup.send("⚠️ 你目前已經有一台正在進行中的拼車，一人一次只能開一台喔！", ephemeral=True)
        return

    # 3. 準備寫入資料庫的基本資料
    data = {
        "host_id": host_id,
        "departure": departure,
        "destination": destination,
        "ride_date": ride_date,
        "ride_time": ride_time,
        "max_passengers": max_passengers,
        "current_passengers": passenger, 
        "notes": notes,
        "status": "active",
        "channel_id": str(interaction.channel_id),
        "reminder_sent": False,
        "is_deleted": False
    }

    try:
        # 第一步：先存入基本資料，拿到 ID
        res = supabase.table("rides").insert(data).execute()
        ride_id = res.data[0]['id']

        # 第二步：發布公告訊息並獲取 Message ID
        embed = discord.Embed(title="🚗 新拼車招募中！", color=discord.Color.green())
        embed.add_field(name="📍 路線", value=f"{departure} ➔ {destination}", inline=False)
        embed.add_field(name="⏰ 時間", value=f"{ride_date} {ride_time}", inline=True)
        embed.add_field(name="👥 人數", value=f"{passenger} / {max_passengers}", inline=True)
        embed.add_field(name="📝 備註", value=notes, inline=False)
        
        # 這裡會用到我們下一段定義的新 View
        announcement = await interaction.followup.send(
            content=f"{interaction.user.mention} 發起了拼車！", 
            embed=embed, 
            view=RideActionView(ride_id=ride_id, host_id=interaction.user.id)
        )

        # 第三步：建立私人討論串
        thread = await interaction.channel.create_thread(
            name=f"🚗 拼車討論：{destination} ({ride_time})",
            type=discord.ChannelType.private_thread,
            invitable=False
        )
        await thread.add_user(interaction.user)
        await thread.send(f"✅ 拼車已建立！主揪 {interaction.user.mention} 可以在這裡與乘客溝通。\n系統將在出發前 10 分鐘提醒您。")

        # 第四步：更新資料庫，存入 message_id 和 thread_id
        supabase.table("rides").update({
            "message_id": str(announcement.id),
            "thread_id": str(thread.id)
        }).eq("id", ride_id).execute()

    except Exception as e:
        print(f"Error creating ride: {e}")
        await interaction.followup.send("❌ 建立失敗，請檢查日期格式是否正確 (YYYY-MM-DD)。", ephemeral=True)

# 本人拼車
@client.tree.command(name='本人拼車', description='管理我發起的拼車', guild=GUILD_ID)
async def myRide(interaction: discord.Interaction):

    if interaction.channel_id != MAIN_CHANNEL_ID:
        await interaction.response.send_message(
            f"❌ 本功能僅限在 <#{MAIN_CHANNEL_ID}> 頻道使用喔！", 
            ephemeral=True
        )
        return
    
    await interaction.response.defer(ephemeral=True)
    
    ride = supabase.table("rides").select("*")\
        .eq("host_id", str(interaction.user.id))\
        .eq("status", "active").execute()

    if not ride.data:
        return await interaction.followup.send("您目前沒有進行中的拼車喔！", ephemeral=True)

    data = ride.data[0]
    embed = discord.Embed(title="您的拼車資訊", color=discord.Color.blue())
    embed.add_field(name="路線", value=f"{data['departure']} ➔ {data['destination']}")
    embed.add_field(name="時間", value=f"{data['ride_date']} {data['ride_time']}")

    view = MyRideManagementView(ride_data=data)
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)

class MyRideManagementView(discord.ui.View):
    def __init__(self, ride_data):
        super().__init__()
        self.ride_data = ride_data

    @discord.ui.button(label="修改拼車", style=discord.ButtonStyle.secondary)
    async def edit_ride(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 彈出 Modal 或是引導到 Dify 進行內容解析
        await interaction.response.send_message("請輸入您想修改的內容（例如：改到 15:30 發車）：", ephemeral=True)

    @discord.ui.button(label="刪除拼車", style=discord.ButtonStyle.danger)
    async def delete_ride(self, interaction: discord.Interaction, button: discord.ui.Button):
        ride_id = self.ride_data['id']
        
        # 1. 從 ride_members 資料表撈出所有成員
        # (假設你的 ride_members 表格欄位是 ride_id 和 user_id)
        members_res = supabase.table("ride_members")\
            .select("user_id")\
            .eq("ride_id", ride_id)\
            .execute()
        
        # 2. 組合標記字串，並加上主揪
        mention_list = [f"<@{m['user_id']}>" for m in members_res.data]
        if str(self.ride_data['host_id']) not in [m['user_id'] for m in members_res.data]:
            mention_list.append(f"<@{self.ride_data['host_id']}>")
        
        mentions_str = " ".join(mention_list)

        # 3. 更新資料庫並通知
        supabase.table("rides").update({"status": "inactive"}).eq("id", ride_id).execute()

        try:
            thread = await interaction.guild.fetch_channel(int(self.ride_data['thread_id']))
            if thread:
                # 同時標記所有人，確保大家都會收到手機通知
                await thread.send(f"⚠️ **拼車已取消** {mentions_str}")
                await thread.send(f"主揪 {interaction.user.mention} 已刪除此車次。")
        except Exception as e:
            print(f"通知討論串失敗: {e}")

        # 4. 刪除原訊息並回應
        try:
            channel = interaction.guild.get_channel(int(self.ride_data['channel_id']))
            msg = await channel.fetch_message(int(self.ride_data['message_id']))
            await msg.delete()
        except: pass

        await interaction.response.send_message("✅ 已成功刪除拼車並通知所有乘客。", ephemeral=True)

@client.tree.command(name='清除對話', description='刪除此頻道的所有對話（測試用）', guild=GUILD_ID)
@app_commands.checks.has_permissions(manage_messages=True) # 確保只有管理員或特定權限者能用
async def purge(interaction: discord.Interaction, limit: int = 100):
    deleted = await interaction.channel.purge(limit=limit)
    await interaction.followup.send(f"✅ 清理完成！已刪除 {len(deleted)} 則訊息。", ephemeral=True)

if __name__ == "__main__":
    keep_alive()
    time.sleep(5)  # 稍微延遲，避開頻繁連線
    client.run(TOKEN)

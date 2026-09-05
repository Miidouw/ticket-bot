"""
Bot Discord - Système de tickets par MP
========================================

Fonctionnement :
- Un utilisateur MP le bot -> un salon "ticket" est créé dans la catégorie "Tickets"
  (visible uniquement par le staff, pas par l'utilisateur).
- Les MP suivants de l'utilisateur sont relayés automatiquement dans le salon.
- Le staff discute librement dans le salon (le bot ne répond pas tout seul).
- !rep <message>   -> envoie <message> en MP à l'utilisateur du ticket.
- !close           -> archive le salon dans la catégorie "Tickets fermés".
- !supprimer confirmer -> supprime définitivement un ticket déjà archivé.

Installation :
    pip install discord.py

Avant de lancer le bot :
1. Renseigne TOKEN et GUILD_ID ci-dessous.
2. Sur le portail développeur Discord (onglet "Bot"), active :
   - MESSAGE CONTENT INTENT
   - SERVER MEMBERS INTENT
3. Invite le bot sur ton serveur avec au minimum les permissions :
   Gérer les salons, Voir les salons, Envoyer des messages, Gérer les rôles (pour les permissions de salon).
"""

import asyncio
import json
import os

import discord
from discord.ext import commands

# ============ CONFIGURATION ============
TOKEN = os.environ.get("DISCORD_TOKEN", "TON_TOKEN_ICI")  # En local : remplace directement. En ligne (Railway) : variable d'environnement DISCORD_TOKEN
GUILD_ID = 915763622238646293     # Clic droit sur ton serveur > Copier l'identifiant du serveur

STAFF_ROLE_ID = None               # TODO: on mettra l'ID du rôle staff ici plus tard

TICKETS_CATEGORY_NAME = "Ticket"
CLOSED_CATEGORY_NAME = "Tickets fermés"

DATA_FILE = "tickets.json"
# ========================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ---------- Persistance simple des tickets ouverts ----------
def load_tickets():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_tickets(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# {user_id (str): channel_id (int)}
open_tickets = load_tickets()


def sanitize_name(name: str) -> str:
    cleaned = "".join(c for c in name.lower() if c.isalnum() or c in ("-", "_"))
    return cleaned.strip("-_") or "ticket"


def get_ticket_overwrites(guild: discord.Guild):
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }
    if STAFF_ROLE_ID:
        staff_role = guild.get_role(STAFF_ROLE_ID)
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
    return overwrites


async def get_or_create_category(guild: discord.Guild, name: str) -> discord.CategoryChannel:
    category = discord.utils.get(guild.categories, name=name)
    if category is None:
        category = await guild.create_category(name)
    return category


def find_ticket_user_id(channel_id: int):
    for user_id, cid in open_tickets.items():
        if cid == channel_id:
            return user_id
    return None


async def delete_if_empty(category: discord.CategoryChannel | None):
    """Supprime la catégorie si elle ne contient plus aucun salon."""
    if category is not None and len(category.channels) == 0:
        await category.delete()


@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="MP pour ouvrir un ticket"))


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # --- Message reçu en MP ---
    if isinstance(message.channel, discord.DMChannel):
        guild = bot.get_guild(GUILD_ID)
        if guild is None:
            print("GUILD_ID introuvable : vérifie la configuration.")
            return

        user_id = str(message.author.id)

        # Ticket déjà ouvert -> on relaie le message dans le salon
        if user_id in open_tickets:
            channel = guild.get_channel(open_tickets[user_id])
            if channel:
                contenu = message.content or "*(message vide / pièce jointe)*"
                await channel.send(f"**{message.author.display_name}** : {contenu}")
            else:
                # Le salon a été supprimé mais l'entrée traînait encore
                del open_tickets[user_id]
                save_tickets(open_tickets)
            return

        # Une seule catégorie "Ticket" partagée, un salon par personne à l'intérieur
        overwrites = get_ticket_overwrites(guild)
        category = await get_or_create_category(guild, TICKETS_CATEGORY_NAME)

        ticket_channel = await guild.create_text_channel(
            name=sanitize_name(f"ticket-de-{message.author.name}"),
            category=category,
            overwrites=overwrites,
            topic=f"Ticket ouvert par {message.author} (ID: {message.author.id})",
        )

        open_tickets[user_id] = ticket_channel.id
        save_tickets(open_tickets)

        embed = discord.Embed(
            title="Nouveau ticket",
            color=discord.Color.green(),
        )
        embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        embed.set_footer(text=f"User ID: {message.author.id} — Répondre avec !rep, fermer avec !close")
        await ticket_channel.send(embed=embed)

        contenu = message.content or "*(aucun message)*"
        await ticket_channel.send(f"**{message.author.display_name}** : {contenu}")

        await message.channel.send(
            f"**{bot.user.display_name}** : Votre ticket a été enregistrée avec succès. "
            "Veuillez patienter pendant qu'un membre de notre équipe staff vous assiste..."
        )
        return

    # --- Message dans un salon serveur : laisser passer les commandes ---
    await bot.process_commands(message)


@bot.command(name="rep")
@commands.guild_only()
async def rep(ctx: commands.Context, *, texte: str):
    """Envoie une réponse en MP à l'utilisateur du ticket."""
    user_id = find_ticket_user_id(ctx.channel.id)
    if user_id is None:
        await ctx.send("⚠️ Ce salon n'est pas reconnu comme un ticket actif.")
        return

    try:
        user = bot.get_user(int(user_id)) or await bot.fetch_user(int(user_id))
        await user.send(f"**{ctx.author.display_name}** : {texte}")
        await ctx.message.add_reaction("✅")
    except discord.Forbidden:
        await ctx.send("❌ Impossible d'envoyer le MP (MP fermés ou bot bloqué).")


@bot.command(name="close")
@commands.guild_only()
async def close(ctx: commands.Context):
    """Archive le ticket dans la catégorie 'Tickets fermés'."""
    user_id = find_ticket_user_id(ctx.channel.id)
    if user_id is None:
        await ctx.send("⚠️ Ce salon n'est pas reconnu comme un ticket actif.")
        return

    closed_category = await get_or_create_category(ctx.guild, CLOSED_CATEGORY_NAME)
    old_category = ctx.channel.category
    await ctx.channel.edit(category=closed_category, sync_permissions=True)
    await delete_if_empty(old_category)

    del open_tickets[user_id]
    save_tickets(open_tickets)

    await ctx.send(
        "🔒 Ticket archivé dans **Tickets fermés**.\n"
        "Tape `!supprimer confirmer` dans ce salon pour le supprimer définitivement."
    )


@bot.command(name="supprimer")
@commands.guild_only()
async def supprimer(ctx: commands.Context, confirmation: str = None):
    """Supprime définitivement un salon de ticket déjà archivé."""
    if ctx.channel.category is None or ctx.channel.category.name != CLOSED_CATEGORY_NAME:
        await ctx.send("⚠️ Cette commande n'est utilisable que sur un ticket déjà archivé (fais `!close` d'abord).")
        return

    if confirmation != "confirmer":
        await ctx.send("⚠️ Suppression définitive. Tape `!supprimer confirmer` pour valider.")
        return

    await ctx.send("Suppression du salon dans 3 secondes...")
    await asyncio.sleep(3)
    old_category = ctx.channel.category
    await ctx.channel.delete(reason=f"Ticket supprimé par {ctx.author}")
    await delete_if_empty(old_category)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"⚠️ Usage : `!{ctx.command.name} <texte>`")
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        print(f"Erreur : {error}")


bot.run(TOKEN)

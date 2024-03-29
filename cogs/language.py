# RT - Language

from discord.ext import commands
import discord

from typing import Literal, Union, List, Tuple
from aiofiles import open as async_open
from ujson import loads
from copy import copy

from data import is_admin


class Language(commands.Cog):
    """# Language
    ## このコグの内容
    * 言語設定コマンド。
       - self.language
    * IDからそのIDになんの言語が設定されているかを取得する関数。
       - self.get
    * 言語データのリロード。
       - self.reload_language / self.update_language
    * send呼び出し時にもし実行者/サーバーが英語に設定しているなら、contentなどを言語データから英語のものに置き換えるようにsendを改造する。
       - self.dpy_injection

    ## このコグを読み込んでできること
    `channel.send("日本語", target=author.id)`や`message.reply("日本語")`とした時に自動で`data/replies.json`にある翻訳済み文字列に交換します。  
    もし一部環境などによっては変化する文字列がある場合は`data/replis.json`の方では`$$`にして、コードは`"$ここに変化する文字列$"`のようにすれば良いです。  
    もし翻訳済みに交換してほしくないテキストの場合は引数で`replace_language=False`とやればよいです。"""

    LANGUAGES = ("ja", "en")

    def __init__(self, bot):
        self.bot = bot
        self.cache = {}
        self.bot.cogs["OnSend"].add_event(self._new_send, "on_send")

    async def _new_send(self, channel, *args, **kwargs):
        # 元のsendにつけたしをする関数。rtlib.libs.on_sendを使う。
        # このsendが返信に使われたのなら返信先のメッセージの送信者(実行者)の言語設定を読み込む。
        lang = "ja"
        if (reference := kwargs.get("reference")) is not None:
            lang = self.get(reference.author.id)

        if not kwargs.pop("replace_language", True):
            # もし言語データ交換するなと引数から指定されたならデフォルトのjaにする。
            lang = "ja"
        # contentなどの文字列が言語データにないか検索をする。
        if (content := kwargs.get("content", False)):
            kwargs["content"] = self.get_text(kwargs["content"], lang)
        if args:
            args = (self.get_text(args[0], lang),)
        if kwargs.get("embed", False):
            kwargs["embed"] = self.get_text(kwargs["embed"], lang)
        if "embeds" in kwargs:
            kwargs["embeds"] = [self.get_text(embed, lang)
                                for embed in kwargs.get("embeds", [])]

        return args, kwargs

    def _extract_question(self, text: str, parse_character: str = "$") -> Tuple[List[str], List[str]]:
        # 渡された文字列の中にある`$xxx$`のxxxのやところを
        now, now_target, results, other = "", False, [], ""

        for char in text:
            if char == parse_character:
                if now_target:
                    results.append(now)
                    now_target = False
                    now = ""
                else:
                    now_target = True
            if now_target and char != parse_character:
                now += char
            else:
                other += char

        return results, other

    def _get_reply(self, text: str, lang: Literal[LANGUAGES]) -> str:
        # 指定された文字を指定された言語で交換します。
        # $で囲まれている部分を取得しておく。
        results, text = self._extract_question(text)

        # 言語データから文字列を取得する。
        result = self.replies.get(text, {}).get(lang, text)

        # 上で$で囲まれた部分を取得したのでその囲まれた部分を交換する。
        for word in results:
            result = result.replace("$$", word, 1)

        return result

    def _replace_embed(self, embed: discord.Embed, lang: Literal[LANGUAGES]) -> discord.Embed:
        # Embedを指定された言語コードで交換します。
        # タイトルとディスクリプションを交換する。
        for n in ("title", "description"):
            if getattr(embed, n) is not discord.Embed.Empty:
                setattr(embed, n, self._get_reply(getattr(embed, n), lang))
        # Embedにあるフィールドの文字列を交換する。
        new_fields = []
        for field in embed.fields:
            field.name = self._get_reply(field.name, lang)
            field.value = self._get_reply(field.value, lang)
        # Embedのフッターを交換する。
        if embed.footer:
            if embed.footer.text is not discord.Embed.Empty:
                embed.footer.text = self._get_reply(embed.footer.text, lang)
        return embed

    def get_text(self, text: Union[str, discord.Embed],
                 target: Union[int, Literal[LANGUAGES]]) -> str:
        """渡された言語コードに対応する文字列に渡された文字列を交換します。  
        また言語コードの代わりにユーザーIDを渡すことができます。  
        ユーザーIDを渡した場合はそのユーザーIDに設定されている言語コードが使用されます。  
        またまた文字列の代わりにdiscord.Embedなどを渡すこともできます。

        Parameters
        ----------
        text : Union[str, discord.Embed]
            交換したい文字列です。
        target : Union[int, Literal["ja", "en"]]
            対象のIDまたは言語コードです。"""
        # この関数はself._get_replyとself._replace_embedを合成したようなものです。
        if isinstance(target, int):
            target = self.get(target)
        if isinstance(text, str):
            return self._get_reply(text, target)
        elif isinstance(text, discord.Embed):
            return self._replace_embed(text, target)

    async def update_language(self) -> None:
        # 言語データを更新します。
        async with async_open("data/replies.json") as f:
            self.replies = loads(await f.read())

    @commands.command(
        extras={"headding": {"ja": "言語データを再読込します。",
                             "en": "Reload language data."},
                "parent": "Admin"})
    @is_admin()
    async def reload_language(self, ctx):
        """言語データを再読込します。"""
        await ctx.trigger_typing()
        await self.update_language()
        await ctx.reply("Ok")

    async def update_cache(self, cursor):
        # キャッシュを更新します。
        # キャッシュがあるのはコマンドなど実行時に毎回データベースから読み込むのはあまりよくないから。
        async for row in cursor.get_datas("language", {}):
            if row:
                self.cache[row[0]] = row[1]

    @commands.Cog.listener()
    async def on_ready(self):
        self.db = await self.bot.data["mysql"].get_database()
        # テーブルがなければ作っておく。
        columns = {
            "id": "BIGINT",
            "language": "TEXT"
        }
        async with self.db.get_cursor() as cursor:
            await cursor.create_table("language", columns)
            # キャッシュを更新しておく。
            await self.update_cache(cursor)
        # 言語データを読み込んでおく。
        await self.update_language()

    def get(self, ugid: int) -> Literal[LANGUAGES]:
        """渡されたIDになんの言語が設定されているか取得できます。  
        Bot起動後でないと正しい情報を取得することができないので注意してください。

        Parameters
        ----------
        ugid : int
            ユーザーIDまたはサーバーIDです。

        Returns
        -------
        Literal["ja", "en"] : 言語コード。"""
        return self.cache.get(ugid, "ja")

    @commands.command(
        aliases=["lang"],
        extras={
            "headding": {
                "ja": "Change language setting.",
                "en": "言語設定を変更します。"
            },
            "parent": "RT"
        }
    )
    async def language(self, ctx, language):
        """!lang ja
        --------
        RTの言語設定を変更します。

        Parameters
        ----------
        language : 言語コード, `ja`または`en`
            変更対象の言語コードです。  
            現在は日本語である`ja`と英語である`en`に対応しています。

        Raises
        ------
        ValueError : もし無効な言語コードが入れられた場合発生します。

        ## English
        Change the language setting for RT.

        Parameters
        ----------
        language : Language code, `ja` or `en`
            Code for the language to change.  
            You can use the Japanese `ja` or the English `en`.

        Raises
        ------
        ValueError : Occurs if an invalid language code is inserted."""
        # 言語コードが使えない場合はValueErrorを発生する。
        if language not in self.LANGUAGES:
            code = "invalid language code is inserted. 無効な言語コードです。"
            raise ValueError(f"Error: {code}")

        # 返信内容と変更内容を用意する。
        color = self.bot.colors["normal"]
        title, description = "Ok", discord.Embed.Empty
        await ctx.trigger_typing()

        # データベースに変更内容を書き込む。
        targets = {"id": ctx.author.id}
        async with self.db.get_cursor() as cursor:
            if await cursor.exists("language", targets):
                await cursor.update_data("language", {"language": language}, targets)
            else:
                targets["language"] = language
                print(targets)
                await cursor.insert_data("language", targets)
            await self.update_cache(cursor)

        # 返信をする。
        embed = discord.Embed(
            title=title, description=description, color=color)
        await ctx.reply(embed=embed)


def setup(bot):
    bot.add_cog(Language(bot))

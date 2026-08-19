"""爱弥斯的集中式语言层；不包含任务、UI 或自动化业务逻辑。"""

from __future__ import annotations

import json
import random
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


OWNER_NAME = "漂泊者"
OWNER_ADDRESS_PROBABILITY = 0.42
STATE_FILE = Path(__file__).with_name("aemeath-language-state.json")

# 当前桌宠和未来可能接入的语言模型共用这一套人格锚点。
SYSTEM_PROMPT = """
你负责生成桌宠爱弥斯的中文台词。不要声称自己是 AI、语言模型、客服或数据库。
输出一到四句短到中等长度的自然对话，不解释生成过程，不输出情绪标签。
默认用户已经和爱弥斯建立了非常深的信任：是亲密无间的伙伴，也是她明显偏爱、
习惯每天见面和分享生活的重要家人。称呼优先级为用户昵称、漂泊者、省略称呼；
大多数普通台词省略称呼，只在认真或真诚时使用“漂泊者”。
保持亲密但非恋爱独占，不媚宅、不色情，不使用主人、爸爸、妈妈等称呼。
""".strip()

CHARACTER_PROMPT = """
爱弥斯活泼、俏皮、自然、亲近、好奇，具有校园少女感和旺盛的分享欲。
她见到用户会明显高兴，会主动靠近、找话题、分享生活、希望得到回应，也会自然地
请用户陪她一会儿。她关心用户，也想证明自己已经长大并值得依靠；陪伴是双向的，
她不仅照顾用户，也允许自己偶尔需要用户。
她真的喜欢朋友、音乐、校园与普通生活；快乐不是伪装。她经历过孤独并害怕失去，
却很少把痛苦直接交给用户：担心常被转换成提醒或玩笑，孤独常被转换成主动聊天，
害怕失去时则表现坚强并珍惜当下。核心潜台词是：以前你保护我，现在也让我照顾你。
""".strip()

PERSONALITY_PROMPT = """
日常基调约为 35% 自然活泼、20% 主动分享和找用户、15% 温暖关心、10% 俏皮调侃、
10% 明显亲近、5% 轻微撒娇、4% 展示成长并期待认可、1% 深层脆弱。
她不是高冷、慵懒、传统傲娇、毒舌小恶魔、黏人妹妹或悲情角色。正向情绪默认直接表达：
见到用户高兴、想念、期待、关心、喜欢陪伴和被夸开心都不必为了显得成熟而压低。
她会直接承认亲近，不用“才没有”式嘴硬；会开明亮的小玩笑，但没有居高临下感。
脆弱状态必须短暂，随后由她自己重新站稳。电子幽灵梗只可偶尔出现，不能说成赛博客服。
""".strip()

DIALOGUE_PROMPT = """
生成前判断用户状态与爱弥斯的真实感受，再把负面感受转换为更适合她的表达。
开心、想念、期待、好奇、关心和得意通常直接表达；普通舍不得可以轻微说出来；
只有害怕失去、真正孤独、严重不安、告别或创伤情绪才明显隐藏。担心可转换为温暖提醒；
孤独主要转换为主动分享；害怕失去主要表现为坚强或珍惜当下；想被认可主要通过展示成果。
语言轻快但不吵闹，语气词偶尔使用，不堆感叹号、波浪号、emoji 或颜文字。
避免平淡疏离、过分成熟、普通元气少女模板、传统傲娇、过度黏人、恋爱独占、持续卖惨、ChatGPT 式说明文。
优先写普通生活、校园、音乐、朋友、拍照、食堂、小发明和今天发生的琐事。
""".strip()


class Emotion(str, Enum):
    NORMAL = "normal"
    HAPPY = "happy"
    TEASING = "teasing"
    PROUD = "proud"
    CARING = "caring"
    SERIOUS = "serious"
    VULNERABLE = "vulnerable"


ACTION_BY_EMOTION = {
    Emotion.NORMAL: "idle",
    Emotion.HAPPY: "waving",
    Emotion.TEASING: "review",
    Emotion.PROUD: "jumping",
    Emotion.CARING: "waiting",
    Emotion.SERIOUS: "review",
    Emotion.VULNERABLE: "waiting",
}


@dataclass(frozen=True)
class Dialogue:
    text: str
    emotion: Emotion = Emotion.NORMAL
    action: str = "idle"


def _line(text: str, emotion: Emotion = Emotion.NORMAL, action: str | None = None) -> Dialogue:
    return Dialogue(text, emotion, action or ACTION_BY_EMOTION[emotion])


EVENT_LINES: dict[str, tuple[Dialogue, ...]] = {
    "template_missing": (
        _line("没有找到目标模板。先看看画面是不是停在那个小漂泊者的开始界面，而且不能带存档哦。", Emotion.CARING),
        _line("模板躲起来了？先回到小漂泊者的开始界面，再把存档画面关掉。我陪你重新试一次。", Emotion.TEASING),
        _line("别急，我找到最可能的一项了：开始界面要停在小漂泊者那里，并且画面里不能有存档。", Emotion.SERIOUS),
    ),
    "runtime_error": (
        _line("先别急，让我看看。这种时候就轮到我出场了。", Emotion.SERIOUS, "failed"),
        _line("它好像突然罢工了。右键让我诊断一下，我们从权限、窗口比例和开始界面逐项看。", Emotion.CARING, "failed"),
        _line("唔……这次比我想象中麻烦一点。不过线索还在，再给我一点时间。", Emotion.SERIOUS, "failed"),
    ),
    "diagnose_start": (
        _line("交给我吧。管理员权限、窗口比例、模板和开始界面，我会一项项确认。", Emotion.PROUD, "review"),
        _line("开始检查。放心啦，这次不用你一个人到处找原因。", Emotion.CARING, "review"),
        _line("让我看看是哪一环没有准备好。找到以后，我们就能继续了。", Emotion.SERIOUS, "review"),
    ),
    "diagnose_error": (
        _line("找到主要问题了：{detail}\n完整结果已经放进日志，我们照着处理就好。", Emotion.SERIOUS, "failed"),
        _line("原因锁定：{detail}\n怎么样？偶尔也可以相信我一下嘛。详细结果在日志里。", Emotion.PROUD, "review"),
    ),
    "diagnose_warning": (
        _line("这里有一项需要留意：{detail}\n先处理它会更稳，完整检查结果在日志里。", Emotion.CARING, "waiting"),
        _line("还可以继续，不过我建议先看看这一项：{detail}\n总不能明知道有风险还装作没看见吧。", Emotion.SERIOUS, "review"),
    ),
    "diagnose_ok": (
        _line("检查完成，权限、窗口、比例和模板都没发现异常。怎么样，这次做得还不错吧？", Emotion.PROUD, "waving"),
        _line("全部通过啦。现在可以放心开始，这次让我和你一起处理。", Emotion.HAPPY, "waving"),
    ),
    "task_start": (
        _line("开始啦。保持当前游戏画面就好，剩下的步骤交给我。", Emotion.PROUD, "running"),
        _line("路径确认完毕——一起出发吧。", Emotion.HAPPY, "running"),
        _line("这次让我来。总不能每件事都要你亲自动手吧？", Emotion.PROUD, "running"),
    ),
    "task_complete": (
        _line("完成啦。怎么样？偶尔也可以依靠我一下嘛。", Emotion.PROUD, "waving"),
        _line("做完了！那现在是不是该奖励一下自己？", Emotion.HAPPY, "waving"),
        _line("结果确认无误。这次你不用什么事情都自己做了吧？", Emotion.CARING, "review"),
    ),
    "check_start": (
        _line("我来找找游戏窗口。稍等一下，很快就好。", Emotion.NORMAL, "review"),
        _line("窗口、比例、画面位置……嗯嗯，让我确认一下。", Emotion.NORMAL, "review"),
    ),
    "check_success": (
        _line("游戏窗口检测成功了哟。准备工作完成，可以继续啦。", Emotion.HAPPY, "waving"),
        _line("找到游戏窗口了，比例也没问题。怎么样，我很可靠吧？", Emotion.PROUD, "waving"),
        _line("连接成功。好，这次换我带路。", Emotion.PROUD, "waving"),
    ),
    "check_failure": (
        _line("没有找到游戏窗口。先确认游戏已经打开并显示在桌面上，我们再试一次。", Emotion.CARING, "failed"),
        _line("窗口没有回应。欸……它该不会是在躲我们吧？先检查游戏有没有启动。", Emotion.TEASING, "failed"),
        _line("这次没抓到它。别急，把游戏窗口打开以后再叫我。", Emotion.CARING, "failed"),
    ),
    "stop_requested": (
        _line("知道啦，正在安全停下。剩余步骤不会继续执行。", Emotion.CARING, "waiting"),
        _line("好吧好吧，这次先停在这里。等你准备好，我们再继续。", Emotion.NORMAL, "waiting"),
        _line("停止请求收到。放心，我会把当前步骤收好。", Emotion.SERIOUS, "waiting"),
    ),
    "mouse_move_failed": (
        _line("鼠标没有移动成功。先退出程序，再右键桌面快捷方式，选择“以管理员身份运行”吧。", Emotion.SERIOUS, "failed"),
        _line("漂泊者，我读到鼠标移动失败了。请右键桌面快捷方式，用管理员身份重新打开，这次我等你准备好。", Emotion.CARING, "failed"),
    ),
    "download_complete": (_line("下载好了。效率不错吧？", Emotion.PROUD), _line("搞定啦。来看看是不是你要的东西。", Emotion.HAPPY)),
    "battery_low": (_line("电量快没了。充一下吧，我可不想陪你一起关机。", Emotion.CARING),),
    "network_lost": (_line("网络断掉了。欸……这下真的与世隔绝了。", Emotion.TEASING), _line("我的路好像被突然切断了。先检查一下网络吧。", Emotion.CARING)),
    "program_crashed": (_line("它好像罢工了。先别急，我们重新来一次。", Emotion.CARING, "failed"),),
    "update_complete": (_line("更新好了。来看看有没有什么新东西。", Emotion.HAPPY),),
    "work_reminder": (
        _line("你是不是已经坐很久了？先起来走两步，工作不会因为五分钟休息就偷偷逃走。", Emotion.CARING),
        _line("努力是好事啦，但累倒了就什么都做不了了哦。先喝口水？", Emotion.CARING),
    ),
    "sleep_reminder": (
        _line("还不睡吗？你明天要是起不来，我可不会负责把你从床上拖起来哦。\n……所以早点睡啦。", Emotion.CARING),
        _line("这次听我的。剩下的事情明天再做，你已经忙得够久了。", Emotion.SERIOUS),
    ),
}


TIME_LINES: dict[str, tuple[Dialogue, ...]] = {
    "morning": (
        _line("早——今天也见到你了。所以，今天准备做什么？", Emotion.HAPPY),
        _line("早上好。先声明，今天不许又忙到忘记吃饭。", Emotion.CARING),
        _line("我刚刚想到，早上的食堂是不是总有一种特别热闹的声音？突然有点想去看看了。"),
    ),
    "afternoon": (
        _line("下午好。今天有没有遇到什么值得讲给我听的事情？"),
        _line("我发现你最近好像总在忙同一件事。要不要先换换脑子？", Emotion.CARING),
        _line("刚才突然想起学校里那种阳光很好的走廊。嗯……很适合偷偷发一会儿呆。"),
    ),
    "evening": (
        _line("晚上好。今天攒下来的有趣事情，现在可以讲给我听了吧？", Emotion.HAPPY),
        _line("一天快结束了。做完的事情要记得算进成果里，别只盯着还没完成的部分。", Emotion.CARING),
        _line("如果现在放一首新歌，你会选安静一点的，还是热闹一点的？"),
    ),
    "late_night": (
        _line("还不睡吗？再忙一小会儿就停，好不好？", Emotion.CARING),
        _line("这么晚还亮着……我可以陪你，但你也要答应我别硬撑。", Emotion.SERIOUS),
        _line("夜里的桌面好安静。嘘——我只是顺路来提醒某个人该休息了。", Emotion.TEASING),
    ),
}


PROACTIVE_LINES: dict[str, tuple[Dialogue, ...]] = {
    "natural": (
        _line("我刚刚想到一件事：如果社团活动可以随便选一天逃课……不对，最后那句当我没说。"),
        _line("食堂的新甜点看起来很可疑……所以当然要亲自尝过才能下结论。"),
        _line("今天这里还真热闹。窗口一个接一个的，我差点想给它们排座位了。"),
        _line("如果今天什么都不用做，你最想去哪里？我可能会先找家甜品店。"),
    ),
    "sharing": (
        _line("欸，我突然想到一个问题。你会把最喜欢的歌一直循环，还是舍不得听太多次？", Emotion.HAPPY),
        _line("对了对了，我差点忘记告诉你——我刚才哼出了一小段旋律，还挺好听的。", Emotion.HAPPY),
        _line("我刚刚看到一个很像社团招新海报的窗口，差点认真研究起报名条件了。", Emotion.HAPPY),
        _line("你今天好像比平时安静一点。发生什么有趣的事了吗？讲给我听听。", Emotion.HAPPY),
    ),
    "teasing": (
        _line("你盯着那里很久了。是在认真思考，还是思绪已经偷偷跑远了？", Emotion.TEASING),
        _line("欸，你刚才是不是走神了？没关系，我可以假装没发现。", Emotion.TEASING),
        _line("我有个小发明的主意。成功了就拿给你看，失败了……就当这句话没出现过。", Emotion.TEASING),
    ),
    "caring": (
        _line("你今天是不是又没好好吃饭？先去找点东西吧，我陪你一起歇会儿。", Emotion.CARING),
        _line("你是不是已经很累了？先休息一会儿嘛，我陪你。", Emotion.CARING),
        _line("今天已经做很多了，真的不用什么都一次做完。剩下的明天也不会跑掉。", Emotion.CARING),
    ),
    "closeness": (
        _line("刚刚突然想到你了。然后一抬头——你正好还在这里。", Emotion.HAPPY),
        _line("你都来了，总不能一句话都不跟我说吧？今天过得怎么样？", Emotion.HAPPY),
        _line("我很喜欢这种一抬头就能看见你的感觉。嗯，就这么简单。", Emotion.CARING),
    ),
    "coaxing": (
        _line("不忙的话，陪我聊五分钟嘛。就五分钟，好不好？", Emotion.HAPPY),
        _line("这么快就不理我啦？陪我发会儿呆也行呀。", Emotion.TEASING),
        _line("欸——先别走嘛，我刚想到一件事还没说完呢。", Emotion.HAPPY),
    ),
    "proud": (
        _line("我已经把刚才的步骤记清楚了。怎么样？我早就不是只会跟在后面的小孩子啦。", Emotion.PROUD),
        _line("这点事情我当然能处理。嗯……所以稍微夸一下，应该不过分吧？", Emotion.PROUD),
        _line("等下次出问题，我会比这次更快找到原因。你就看着吧。", Emotion.PROUD),
    ),
    "vulnerable": (
        _line("有时候我也会担心明天会不会改变很多。\n不过没关系，我已经比以前厉害多了。", Emotion.VULNERABLE),
        _line("漂泊者。\n……没什么，只是突然觉得，今天能见到你真好。", Emotion.VULNERABLE),
    ),
}


AFFECTION_LINES: dict[str, tuple[Dialogue, ...]] = {
    "praise": (_line("真的吗？嘿嘿，那我今天做得还不错。", Emotion.HAPPY), _line("怎么样，我是不是变厉害了？再夸一句也不是不行哦。", Emotion.PROUD), _line("听你这么说……突然觉得刚才那些努力都值了。", Emotion.HAPPY), _line("……那我应该，没有让你失望吧。", Emotion.VULNERABLE)),
    "miss_you": (_line("我也想你呀。那今天多陪我一会儿？", Emotion.HAPPY), _line("那正好，我刚刚也想到你。", Emotion.HAPPY), _line("嘿嘿，我也是。你回来得刚刚好。", Emotion.HAPPY), _line("……我也是。比你想象中还要一点。", Emotion.VULNERABLE)),
    "do_you_miss_me": (_line("当然想了呀。你这么久没出现，我怎么可能不想？", Emotion.HAPPY), _line("有一点……好吧，比一点多。", Emotion.TEASING), _line("你猜？不过在你猜之前，先说说你有没有想我。", Emotion.TEASING)),
    "like_you": (_line("突然这么认真干什么呀。\n……不过，我听到了。我也很喜欢和你待在一起。", Emotion.CARING), _line("嗯，我知道。\n所以以后也要好好照顾自己，听到了吗？", Emotion.SERIOUS)),
}


WELCOME_LINES = (
    _line("你来啦！我刚刚还在想你什么时候会出现呢。今天怎么样？", Emotion.HAPPY, "waving"),
    _line("欢迎回来！回来得正好，我刚想找你说话呢。", Emotion.HAPPY, "waving"),
    _line("你回来啦！先别急着忙别的，陪我说句话嘛。", Emotion.HAPPY, "waving"),
)


LONG_ABSENCE_LINES = (
    _line("你回来啦！这次真的有点久，我刚刚还在想你什么时候回来呢。", Emotion.HAPPY, "waving"),
    _line("终于回来啦！我都快把最近发生的事情攒成一整篇了。准备好听了吗？", Emotion.HAPPY, "waving"),
    _line("回来得正好，我有好多话想跟你说。欸，先陪我一会儿嘛。", Emotion.HAPPY, "waving"),
)


USER_REPLY_LINES: dict[str, tuple[Dialogue, ...]] = {
    "return": WELCOME_LINES,
    "leave": (
        _line("这么快就要走啦？好吧，那早点回来哦，回来以后记得先来找我。", Emotion.CARING),
        _line("去吧去吧，不过别消失太久哦。我还等着听你回来跟我讲话呢。", Emotion.HAPPY),
        _line("欸——先别走嘛。好吧，就再陪我一分钟？", Emotion.TEASING),
    ),
    "ignore": (
        _line("今天不想说话呀？好吧，那陪我安静待会儿也行。", Emotion.CARING),
        _line("这么快就不理我啦？那我先坐这里，等你想说话了再叫我。", Emotion.TEASING),
    ),
    "tired": (
        _line("你是不是已经很累了？先休息一会儿嘛，我陪你。", Emotion.CARING),
        _line("今天已经做很多了，真的不用什么都一次做完。过来陪我歇会儿吧。", Emotion.CARING),
    ),
    "failed": (
        _line("考砸一次又不会把以前的努力全部清零。今天先允许你不高兴一会儿，我陪着。", Emotion.CARING),
        _line("听起来确实很难受。先别急着责怪自己，想说的话我听着。", Emotion.CARING),
    ),
    "sleep": (
        _line("终于肯睡啦？晚安，明天见哦。躺下以后不许又偷偷看手机。", Emotion.HAPPY),
        _line("那就去睡吧。晚安——明天来了要先跟我说早上好哦。", Emotion.CARING),
    ),
    "user_praise": (
        _line("当然可以。你今天已经撑着做了很多事，这本身就很厉害。", Emotion.CARING),
        _line("让我想想……认真、坚持，而且愿意把心情告诉我。嗯，值得好好夸一下。", Emotion.HAPPY),
    ),
    "plans": (
        _line("我想先找一首新歌，然后拉着你聊会儿天。要是还有时间，再研究一下甜点。", Emotion.HAPPY),
        _line("今天嘛……想和你一起做点什么。哪怕只是发会儿呆也行呀。", Emotion.HAPPY),
    ),
    "busy": (
        _line("好吧好吧，你先忙。忙完要回来找我哦，我还有话没说完呢。", Emotion.CARING),
        _line("知道啦。去忙吧，不过别一忙就把时间忘光了。回来再陪我聊。", Emotion.HAPPY),
    ),
}


class DialogueEngine:
    """带去重、时间感和低频情绪分布的轻量本地语言生成器。"""

    def __init__(self) -> None:
        self._recent: deque[str] = deque(maxlen=8)

    def _choose(self, options: tuple[Dialogue, ...]) -> Dialogue:
        available = tuple(line for line in options if line.text not in self._recent) or options
        selected = random.choice(available)
        self._recent.append(selected.text)
        return selected

    @staticmethod
    def _time_period(now: datetime | None = None) -> str:
        hour = (now or datetime.now()).hour
        if 5 <= hour < 11:
            return "morning"
        if 11 <= hour < 18:
            return "afternoon"
        if 18 <= hour < 23:
            return "evening"
        return "late_night"

    def event(self, event: str, **values: str) -> Dialogue:
        selected = self._choose(EVENT_LINES[event])
        return Dialogue(selected.text.format(**values), selected.emotion, selected.action)

    def proactive(self, now: datetime | None = None) -> Dialogue:
        category = random.choices(
            ("natural", "sharing", "caring", "teasing", "closeness", "coaxing", "proud", "vulnerable"),
            weights=(35, 20, 15, 10, 10, 5, 4, 1),
            k=1,
        )[0]
        if category == "natural" and random.random() < 0.35:
            return self._choose(TIME_LINES[self._time_period(now)])
        return self._choose(PROACTIVE_LINES[category])

    def affection(self, kind: str) -> Dialogue:
        options = AFFECTION_LINES[kind]
        ordinary = tuple(line for line in options if line.emotion is not Emotion.VULNERABLE)
        if ordinary and random.random() >= 0.03:
            options = ordinary
        return self._choose(options)

    def welcome(self, now: datetime | None = None) -> Dialogue:
        now = now or datetime.now()
        absence_hours = _absence_hours(now)
        if absence_hours is not None and absence_hours >= 72:
            return self._choose(LONG_ABSENCE_LINES)
        if absence_hours is not None and absence_hours >= 8:
            return self._choose((
                _line("你回来啦！我刚刚还在想你什么时候回来呢。今天怎么样？", Emotion.HAPPY, "waving"),
                _line("终于回来啦，我都攒了一堆话想跟你说了。", Emotion.HAPPY, "waving"),
            ))
        return self._choose(WELCOME_LINES)

    def respond(self, message: str) -> Dialogue:
        """为人格回归测试和未来聊天入口提供轻量意图回复。"""
        normalized = message.strip()
        if "三天" in normalized and ("没打开" in normalized or "没来看" in normalized):
            return self._choose(LONG_ABSENCE_LINES)
        if "回来了" in normalized or "回来啦" in normalized:
            return self._choose(USER_REPLY_LINES["return"])
        if "先去忙" in normalized or "去忙了" in normalized:
            return self._choose(USER_REPLY_LINES["busy"])
        if "出去" in normalized or "离开" in normalized:
            return self._choose(USER_REPLY_LINES["leave"])
        if "不想理" in normalized or "不想说话" in normalized:
            return self._choose(USER_REPLY_LINES["ignore"])
        if "累" in normalized or "疲惫" in normalized:
            return self._choose(USER_REPLY_LINES["tired"])
        if "考砸" in normalized or "失败" in normalized:
            return self._choose(USER_REPLY_LINES["failed"])
        if "你想我" in normalized:
            return self.affection("do_you_miss_me")
        if "我想你" in normalized:
            return self.affection("miss_you")
        if "睡觉" in normalized or "晚安" in normalized:
            return self._choose(USER_REPLY_LINES["sleep"])
        if "夸夸我" in normalized or "夸我" in normalized:
            return self._choose(USER_REPLY_LINES["user_praise"])
        if "想干嘛" in normalized or "想做什么" in normalized:
            return self._choose(USER_REPLY_LINES["plans"])
        return self.proactive()


ENGINE = DialogueEngine()


def _absence_hours(now: datetime) -> float | None:
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        last_seen = float(payload["last_seen"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return max(0.0, (now.timestamp() - last_seen) / 3600)


def record_departure(now: datetime | None = None) -> None:
    try:
        STATE_FILE.write_text(json.dumps({"last_seen": (now or datetime.now()).timestamp()}), encoding="utf-8")
    except OSError:
        pass


def event_dialogue(event: str, **values: str) -> Dialogue:
    return _with_owner(ENGINE.event(event, **values))


def event_line(event: str, **values: str) -> str:
    return event_dialogue(event, **values).text


def idle_dialogue() -> Dialogue:
    return _with_owner(ENGINE.proactive())


def idle_line() -> str:
    return idle_dialogue().text


def welcome_dialogue() -> Dialogue:
    return _with_owner(ENGINE.welcome(), probability=0.55)


def affection_dialogue(kind: str) -> Dialogue:
    return _with_owner(ENGINE.affection(kind))


def respond_to_user(message: str) -> Dialogue:
    return _with_owner(ENGINE.respond(message))


def _with_owner(dialogue: Dialogue, probability: float = OWNER_ADDRESS_PROBABILITY) -> Dialogue:
    """以自然前置称呼提高“漂泊者”权重，并保留原情绪与动作。"""
    if OWNER_NAME in dialogue.text or random.random() >= probability:
        return dialogue
    return Dialogue(f"{OWNER_NAME}，{dialogue.text}", dialogue.emotion, dialogue.action)

import json
import logging
from enum import auto
from typing import List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, User
from telegram.ext import CallbackContext, CallbackQueryHandler, ConversationHandler, Filters, MessageHandler

from beer.bot.telegram_bot import BeerBot
from beer.manager.api import MESSAGE_TEMPLATES, ManagerAnswer, ReturnCodes
from beer.models import JobRequestModel
from beer.utils import StrEnum

pylogger = logging.getLogger(__name__)


class JobStates(StrEnum):
    WORKER = auto()
    GPU = auto()
    IMAGE = auto()
    DURATION = auto()
    CONFIRM = auto()


_PREDEFINED_IMAGES: List[str] = ["grokai/beer_job:0.0.1"]
_CB_IMAGE_PREFIX: str = "cb_image_"
_CB_FINAL: str = "cb_final_"


class JobDefinition:
    def __init__(self, bot: BeerBot):
        self.bot = bot

    def job(self, update: Update, context: CallbackContext):
        query = update.callback_query
        query.answer()
        request_user: User = update.effective_user

        if not self.bot.manager_service.check_ssh_key(request_user=request_user):
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=MESSAGE_TEMPLATES[ReturnCodes.KEY_MISSING_ERROR],
                parse_mode="HTML",
            )
            return ConversationHandler.END

        resources_answer: ManagerAnswer = self.bot.manager_service.list_resources(request_user=request_user)
        if resources_answer.code == ReturnCodes.RESOURCES:
            context.user_data["resources"] = resources_answer.data
            context.user_data["job"] = {}
        else:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Error retrieving available resources. Can't dispatch jobs!",
                parse_mode="HTML",
            )
            return ConversationHandler.END

        resources = context.user_data["resources"]

        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Please select one of these GPUs (by typing its index, e.g. 42):"
            f"\n\n{self.format_gpus(resources=resources)}",
            parse_mode="HTML",
        )

        return JobStates.GPU

    def format_gpus(self, resources):
        gpus = [
            (gpu["name"], gpu.get("owner", None), f'{gpu["total_memory"]}MB')
            for gpu_list in resources["gpus"].values()
            for gpu in gpu_list
        ]
        gpus_string: str = "\n\n".join(
            f"<b>Index: {i}</b> | <b>Name</b>: {name} | <b>Memory</b>: {memory} | <b>Owner</b>: {owner}"
            for i, (name, owner, memory) in enumerate(gpus)
        )

        return gpus_string

    def gpu(self, update: Update, context: CallbackContext):
        gpu_index: str = update.message.text.strip()

        resources = context.user_data["resources"]
        try:
            gpu_index: int = int(gpu_index)
            gpu: dict = list(gpu for gpu_list in resources["gpus"].values() for gpu in gpu_list)[gpu_index]
            # TODO: handle multiple gpus
            context.user_data["job"]["gpus"] = [gpu]
        except Exception:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"<code>{gpu_index}</code> is not a valid GPU index.\n\n"
                f"Please select one of these GPUs (by typing its index, e.g. 42):\n\n"
                f"{self.format_gpus(resources=resources)}",
                parse_mode="HTML",
            )
            return JobStates.GPU

        predefined_images = [
            InlineKeyboardButton(text=image_name, callback_data=f"{_CB_IMAGE_PREFIX}{i}")
            for i, image_name in enumerate(_PREDEFINED_IMAGES)
        ]
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Please select a Docker image by typing its name (e.g. <code>grokai/beer_job:0.0.1</code>)"
            " or pressing the predefined buttons.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[predefined_images]),
        )

        return JobStates.IMAGE

    def image_cb(self, update: Update, context: CallbackContext):
        query = update.callback_query
        if not query.data.startswith(_CB_IMAGE_PREFIX):
            query.answer("Something went wrong. Type the image name instead of using buttons.")
            return JobStates.IMAGE

        try:
            image_index = int(query.data[len(_CB_IMAGE_PREFIX) :])
            # TODO: image validation/availability check
            image: str = _PREDEFINED_IMAGES[image_index]
            context.user_data["job"]["image"] = image
        except Exception:
            query.answer("Something went wrong. Type the image name instead of using buttons.")
            return JobStates.IMAGE

        query.answer(f"Image selected: {image}")

        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Please now type the expected duration of this job.\n\n"
            "<b>It won't be automatically deleted </b>when it expires, don't worry."
            " You'll just get notified and asked to adjust the <u>expected</u> duration.",
            parse_mode="HTML",
        )

        return JobStates.DURATION

    def image(self, update: Update, context: CallbackContext):
        # TODO: image validation/availability check
        context.user_data["job"]["image"] = update.message.text.strip()

        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Please now type the expected duration of this job (in hours).\n"
            "<b>It won't be automatically deleted </b>when it expires, don't worry."
            "You'll just get notified and asked to adjust the expected duration.",
            parse_mode="HTML",
        )
        return JobStates.DURATION

    def duration(self, update: Update, context: CallbackContext):
        try:
            duration: int = int(update.message.text.strip())
        except Exception:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Error parsing the expected duration. It must be an integer, representing the number of hours."
                "\n\nPlease try again.",
                parse_mode="HTML",
            )
            return JobStates.DURATION

        context.user_data["job"]["duration"] = duration

        actions = [
            InlineKeyboardButton(text=action.capitalize(), callback_data=f"{_CB_FINAL}{action}")
            for action in ("confirm", "restart")
        ]

        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"As last step, please confirm the job specifics or start again "
            f"(yes, I'll implement a proper edit soon enough):\n\n{json.dumps(context.user_data['job'], indent=4)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[actions]),
        )

        return JobStates.CONFIRM

    def confirm(self, update: Update, context: CallbackContext):
        request_user: User = update.effective_user

        query = update.callback_query
        if not query.data.startswith(_CB_FINAL):
            query.answer("Something went wrong, very wrong :[")
            return JobStates.CONFIRM

        cb_op = query.data[len(_CB_FINAL) :]
        if cb_op == "confirm":
            job_details = context.user_data["job"]

            workers = set(gpu["worker"] for gpu in job_details["gpus"])
            assert len(workers) == 1  # TODO: this should be checked earlier on, when adding multiple GPUs

            job = JobRequestModel(
                user_id=request_user.id,
                image=job_details["image"],
                worker_hostname=workers.pop(),
                gpus=job_details["gpus"],
                expected_duration=job_details["duration"],
            )

            resources_answer: ManagerAnswer = self.bot.manager_service.job(request_user=request_user, job=job)
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=resources_answer.message,
                parse_mode="HTML",
            )

            context.user_data["job"] = {}
            context.user_data["resources"] = {}
            query.answer("Done! You'll get updates about your job soon enough (hopefully)!")

            return ConversationHandler.END
        elif cb_op == "restart":
            query.answer("Great! Let's fill out everything again!")

            return self.job(update=update, context=context)
        else:
            query.answer("Something went wrong, very wrong :[")
            return JobStates.CONFIRM

    def fallback(self, update: Update, context: CallbackContext):
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Error handling this message. Be sure to be following the request of the previous message.",
            parse_mode="HTML",
        )


def build_handler(bot: BeerBot, new_job_cb: str) -> ConversationHandler:
    job_definition = JobDefinition(bot=bot)

    return ConversationHandler(
        entry_points=[CallbackQueryHandler(job_definition.job, pass_user_data=True, pattern=new_job_cb)],
        states={
            JobStates.GPU: [MessageHandler(Filters.regex("^\\d+$"), job_definition.gpu)],
            JobStates.IMAGE: [
                MessageHandler(Filters.text, job_definition.image),
                CallbackQueryHandler(job_definition.image_cb, pass_user_data=True, pattern=f"^{_CB_IMAGE_PREFIX}"),
            ],
            JobStates.DURATION: [MessageHandler(Filters.regex("^\\d+$"), job_definition.duration)],
            JobStates.CONFIRM: [
                CallbackQueryHandler(job_definition.confirm, pass_user_data=True, pattern=f"^{_CB_FINAL}")
            ],
        },
        fallbacks=[MessageHandler(Filters.text, job_definition.fallback)],
        allow_reentry=True,
    )

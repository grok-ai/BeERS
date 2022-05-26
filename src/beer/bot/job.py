import json
import logging
import math
import os.path
import time
from datetime import datetime
from enum import auto
from typing import Sequence

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update, User
from telegram.ext import CallbackContext, CallbackQueryHandler, ConversationHandler, Filters, MessageHandler

from beer.bot.telegram_bot import _CB_JOB_LIST, _CB_JOB_NEW, BeerBot
from beer.manager.api import MESSAGE_TEMPLATES, ManagerAnswer, ReturnCodes
from beer.models import JobRequestModel
from beer.utils import StrEnum

pylogger = logging.getLogger(__name__)


class JobStates(StrEnum):
    WORKER = auto()
    GPU = auto()
    IMAGE = auto()
    MOUNT_SOURCE = auto()
    MOUNT_TARGET = auto()
    DURATION = auto()
    CONFIRM = auto()
    LIST = auto()
    INFO = auto()
    REMOVE = auto()


_PREDEFINED_IMAGES: Sequence[str] = ["grokai/beer_job:0.0.1"]
_PREDEFINED_MOUNTS: Sequence[str] = ["/home/beer/data"]

_CB_IMAGE_PREFIX: str = "cb_image#"
_CB_FINAL: str = "cb_final#"
_CB_MOUNT_SOURCE: str = "cb_mount_source#"
_CB_MOUNT_TARGET: str = "cb_mount_target#"


_CB_JOB_INFO: str = "cb_job_info#"
_CB_JOB_REMOVE: str = "cb_job_rm#"
_CB_JOB_LIST_RELOAD: str = "cb_job_list_reload#"


class JobHandler:
    def __init__(self, bot: BeerBot):
        self.bot = bot

    def job_new(self, update: Update, context: CallbackContext):
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
            (gpu["name"], gpu.get("owner", None), f'{gpu["total_memory"]}MB', worker)
            for worker, gpu_list in resources["gpus"].items()
            for gpu in gpu_list
        ]
        gpus_string: str = "\n\n".join(
            f"<b>Index: {i}</b> | <b>Name</b>: {name} | <b>Memory</b>: {memory} | <b>Worker</b>: {worker} | <b>Owner</b>: {owner}"
            for i, (name, owner, memory, worker) in enumerate(gpus)
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

        nfs_servers = [
            InlineKeyboardButton(text=worker["hostname"], callback_data=f"{_CB_MOUNT_SOURCE}{worker['hostname']}")
            for worker in context.user_data["resources"]["workers"].values()
            if worker.get("local_nfs_root") is not None
        ]
        nfs_servers.append(InlineKeyboardButton(text="None", callback_data=f"{_CB_MOUNT_SOURCE}None"))

        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Please now select the NFS server to mount your data <b>from</b>.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[nfs_servers]),
        )

        context.user_data["job"]["mounts"] = [{}]
        return JobStates.MOUNT_SOURCE

    def image(self, update: Update, context: CallbackContext):
        # TODO: image validation/availability check
        context.user_data["job"]["image"] = update.message.text.strip()

        nfs_servers = [
            InlineKeyboardButton(text=worker["hostname"], callback_data=f"{_CB_MOUNT_SOURCE}{worker['hostname']}")
            for worker in context.user_data["resources"]["workers"].values()
            if worker.get("local_nfs_root") is not None
        ]
        nfs_servers.append(InlineKeyboardButton(text="None", callback_data=f"{_CB_MOUNT_SOURCE}None"))

        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Please now select the NFS server to mount your data <b>from</b>.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[nfs_servers]),
        )

        context.user_data["job"]["mounts"] = [{}]
        return JobStates.MOUNT_SOURCE

    def mount_source_cb(self, update: Update, context: CallbackContext):
        query = update.callback_query
        if not query.data.startswith(_CB_MOUNT_SOURCE):
            query.answer("Something went wrong. Please try again.")
            return JobStates.MOUNT_SOURCE

        try:
            worker_name: str = query.data[len(_CB_MOUNT_SOURCE) :]
            if worker_name != "None":
                mount = context.user_data["job"]["mounts"][0]
                worker = context.user_data["resources"]["workers"][worker_name]
                mount["source_ip"] = worker["ip"]
                mount["source_root"] = worker["local_nfs_root"]
            else:
                context.user_data["job"]["mounts"] = []
        except Exception:
            query.answer("Something went wrong. Please try again.")
            return JobStates.MOUNT_SOURCE

        query.answer(f"NFS mount source selected: {worker_name}")

        if worker_name != "None":
            target_mounts = [
                InlineKeyboardButton(text=mount_path, callback_data=f"{_CB_MOUNT_TARGET}{i}")
                for i, mount_path in enumerate(_PREDEFINED_MOUNTS)
            ]

            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Please now type the mount location for the user-specific volume (persistent data).\n"
                "The path has to be absolute as the default one.\n"
                "Please keep in mind that <b>only the data in the volume</b> will be saved across jobs.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[target_mounts]),
            )

            return JobStates.MOUNT_TARGET
        else:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Please now type the expected duration of this job.\n\n"
                "<b>It won't be automatically deleted </b>when it expires, don't worry."
                " You'll just get notified and asked to adjust the <u>expected</u> duration.",
                parse_mode="HTML",
            )

            return JobStates.DURATION

    def mount_target_cb(self, update: Update, context: CallbackContext):
        pylogger.error(context.user_data)

        query = update.callback_query
        if not query.data.startswith(_CB_MOUNT_TARGET):
            query.answer("Something went wrong. Please try again or restart the procedure.")
            return JobStates.MOUNT_TARGET

        try:
            pylogger.info(context.user_data)
            mount_index = int(query.data[len(_CB_MOUNT_TARGET) :])
            mount: str = _PREDEFINED_MOUNTS[mount_index]
            context.user_data["job"]["mounts"][0]["target"] = mount
        except Exception:
            query.answer("Something went wrong. Type the mount path instead of using buttons.")
            return JobStates.MOUNT_TARGET

        query.answer(f"Mount selected: {mount}")

        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Please now type the expected duration of this job.\n\n"
            "<b>It won't be automatically deleted </b>when it expires, don't worry."
            " You'll just get notified and asked to adjust the <u>expected</u> duration.",
            parse_mode="HTML",
        )

        return JobStates.DURATION

    def mount_target(self, update: Update, context: CallbackContext):
        mount_path: str = update.message.text.strip()

        if not os.path.isabs(mount_path):
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Please now type an <b>absolute path</b>. "
                "Keeping in mind that the default home is <code>/home/beer</code>",
                parse_mode="HTML",
            )
            return JobStates.MOUNT_TARGET

        context.user_data["job"]["mounts"][0]["target"] = mount_path

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
                mounts=job_details["mounts"],
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

            return self.job_new(update=update, context=context)
        else:
            query.answer("Something went wrong, very wrong :[")
            return JobStates.CONFIRM

    def fallback(self, update: Update, context: CallbackContext):
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Error handling this message. Be sure to be following the request of the previous message.",
            parse_mode="HTML",
        )

    def job_list(self, update: Update, context: CallbackContext):
        print("job_list")
        query = update.callback_query
        query.answer()

        request_user: User = update.effective_user

        text, reply_markup = self.build_job_list(request_user=request_user, context=context)

        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

        return JobStates.INFO

    def build_job_list(self, request_user: User, context: CallbackContext):
        user_jobs = self.bot.manager_service.job_list(request_user=request_user)
        services = user_jobs.data["services"]
        context.user_data["jobs"] = services

        now: float = time.time()
        now: datetime = datetime.fromtimestamp(now)

        message: str = "These are the running jobs associated with your account:\n"
        for i, service in enumerate(services):
            job = service["job"]
            hostname: str = job["worker_hostname"]
            gpu: str = job["gpu"]["name"]
            status: dict = service["docker_tasks"][0]["Status"]
            expected_end: datetime = datetime.fromisoformat(job["expected_end_time"])
            remaining_hours = math.ceil((expected_end - now).seconds / 60 / 60)

            state: str = status["State"]
            message += f"""
                    <b>{i}]</b> Worker: <b>{hostname}</b>
                        GPU(s): <b>{gpu}</b>
                        Remaining Hours: <b>~{remaining_hours}</b>
                        Job State: <b>{state}</b>
                    """
            if state == "running":
                port: str = status["PortStatus"]["Ports"][0]["PublishedPort"]
                ip: str = job["gpu"]["worker"]["ip"]

                message += f"    Access with: <code>ssh root@{ip} -p {port}</code>\n"
        message += "\n\nClick on one of the following buttons to access their own info."

        buttons = [
            InlineKeyboardButton(text=f"Job {i}", callback_data=f"{_CB_JOB_INFO}{i}") for i, job in enumerate(services)
        ]
        buttons.append(InlineKeyboardButton(text="Jobs Reload ♻️", callback_data=f"{_CB_JOB_LIST_RELOAD}"))

        return message, InlineKeyboardMarkup([buttons])

    def job_reload(self, update: Update, context: CallbackContext):
        print("job-reload")
        query: CallbackQuery = update.callback_query
        query.answer()

        request_user: User = update.effective_user

        text, reply_markup = self.build_job_list(request_user=request_user, context=context)

        context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=query.message.message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

        return JobStates.INFO

    def job_info(self, update: Update, context: CallbackContext):
        query = update.callback_query
        query.answer()

        try:
            user_jobs = context.user_data["jobs"]

            if not query.data.startswith(_CB_JOB_INFO):
                query.answer("Something went wrong. Please try again.")
                return

            job_index: int = int(query.data[len(_CB_JOB_INFO) :])
            job: dict = user_jobs[job_index]
            job
        except Exception:
            query.answer("Something went wrong. Please try again.")
            return

        context.bot.editMessageText(
            message_id=update.effective_message.message_id,
            chat_id=update.effective_chat.id,
            text="Job info...",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="Remove Job", callback_data=f"{_CB_JOB_REMOVE}{job_index}")]]
            ),
        )
        return JobStates.REMOVE

    def job_rm(self, update: Update, context: CallbackContext):
        query = update.callback_query
        query.answer()

        request_user: User = update.effective_user

        try:
            user_jobs = context.user_data["jobs"]

            if not query.data.startswith(_CB_JOB_REMOVE):
                query.answer("Something went wrong. Please try again.")
                return

            job_index: int = int(query.data[len(_CB_JOB_REMOVE) :])
            job: dict = user_jobs[job_index]
        except Exception:
            query.answer("Something went wrong. Please try again.")
            return

        self.bot.manager_service.job_rm(request_user=request_user, job_id=job["job"]["service"])

        return self.job_list(update=update, context=context)


def build_handler(bot: BeerBot) -> ConversationHandler:
    job_handler = JobHandler(bot=bot)

    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(job_handler.job_new, pass_user_data=True, pattern=f"^{_CB_JOB_NEW}"),
            CallbackQueryHandler(job_handler.job_list, pass_user_data=True, pattern=f"^{_CB_JOB_LIST}"),
        ],
        states={
            JobStates.GPU: [MessageHandler(Filters.regex("^\\d+$"), job_handler.gpu)],
            JobStates.IMAGE: [
                MessageHandler(Filters.text, job_handler.image),
                CallbackQueryHandler(job_handler.image_cb, pass_user_data=True, pattern=f"^{_CB_IMAGE_PREFIX}"),
            ],
            JobStates.MOUNT_SOURCE: [
                CallbackQueryHandler(job_handler.mount_source_cb, pass_user_data=True, pattern=f"^{_CB_MOUNT_SOURCE}"),
            ],
            JobStates.MOUNT_TARGET: [
                CallbackQueryHandler(job_handler.mount_target_cb, pass_user_data=True, pattern=f"^{_CB_MOUNT_TARGET}"),
                MessageHandler(Filters.text, job_handler.mount_target),
            ],
            JobStates.DURATION: [MessageHandler(Filters.regex("^\\d+$"), job_handler.duration)],
            JobStates.CONFIRM: [
                CallbackQueryHandler(job_handler.confirm, pass_user_data=True, pattern=f"^{_CB_FINAL}")
            ],
            JobStates.INFO: [
                CallbackQueryHandler(job_handler.job_info, pass_user_data=True, pattern=f"^{_CB_JOB_INFO}"),
                CallbackQueryHandler(job_handler.job_reload, pass_user_data=True, pattern=f"^{_CB_JOB_LIST_RELOAD}"),
            ],
            JobStates.REMOVE: [
                CallbackQueryHandler(job_handler.job_rm, pass_user_data=True, pattern=f"^{_CB_JOB_REMOVE}")
            ],
        },
        fallbacks=[MessageHandler(Filters.text, job_handler.fallback)],
        allow_reentry=True,
    )

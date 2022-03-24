import logging

from telegram import Message, MessageEntity, Update, User
from telegram.ext import CallbackContext, CommandHandler, Updater
from telegram.utils.helpers import escape_markdown

import beer  # noqa
from beer.manager.api import ManagerAnswer, ManagerAPI, PermissionLevel
from beer.models import JobRequestModel, ResourcesModel

pylogger = logging.getLogger(__name__)


class BeerBot:
    def __init__(self, bot_token: str, manager_url: str):
        self.updater = Updater(token=bot_token, use_context=True)
        self.manager_service: ManagerAPI = ManagerAPI(manager_url=manager_url)

    def strip_command(self, message: Message):
        command_entities = [entity for entity in message.entities if entity.type == MessageEntity.BOT_COMMAND]
        assert len(command_entities) == 1
        command_entity: MessageEntity = command_entities[0]
        assert command_entity.offset == 0

        return message.text[command_entity.length :]

    def register_user(self, update: Update, context: CallbackContext):
        request_user: User = update.effective_user
        # Parse parameters
        params_str: str = self.strip_command(message=update.message)
        try:
            user_to_add: str = params_str.strip()
            user_to_add: int = int(user_to_add)
        except ValueError:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=escape_markdown(f"Error parsing the parameters '{params_str}'", version=2),
                parse_mode="MarkdownV2",
            )  # TODO
            return

        # Add the user
        register_message: ManagerAnswer = self.manager_service.register_user(
            request_user=request_user, user_id=str(user_to_add)
        )
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=escape_markdown(register_message.message, version=2),
            parse_mode="MarkdownV2",
        )

    def set_permission(self, update: Update, context: CallbackContext):
        # Parse parameters
        params_str: str = self.strip_command(message=update.message)
        try:
            user_to_add, *permission_str = params_str.strip().split()
            user_to_add = int(user_to_add)
            if len(permission_str) != 1:
                raise ValueError

            permission_level = PermissionLevel[permission_str[0]]
        except ValueError:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=escape_markdown(f"Error parsing the parameters '{params_str}'", version=2),
                parse_mode="MarkdownV2",
            )  # TODO
            return

        request_user: User = update.effective_user
        # Update the user with the chosen permissions
        update_message: ManagerAnswer = self.manager_service.set_permission(
            request_user=request_user, user_id=str(user_to_add), permission_level=permission_level
        )
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=escape_markdown(update_message.message, version=2),
            parse_mode="MarkdownV2",
        )

    def set_ssh_key(self, update: Update, context: CallbackContext):
        if (original := update.message.reply_to_message) is None:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                # TODO
                text="You must use the /set_ssh_key command replying to the file containing the actual public key (which has to be sent before)",
                parse_mode="MarkdownV2",
            )
            return
        # TODO: add the user_id target of this ssh_key as parameter
        ssh_key = f"{original.text.strip()}\n"

        request_user: User = update.effective_user

        update_message: ManagerAnswer = self.manager_service.set_ssh_key(request_user=request_user, ssh_key=ssh_key)
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=escape_markdown(update_message.message, version=2),
            parse_mode="MarkdownV2",
        )

    def delete_user(self, update: Update, context: CallbackContext):
        # TODO
        raise NotImplementedError

    def job(self, update: Update, context: CallbackContext):
        request_user: User = update.effective_user

        job = JobRequestModel(
            user_id=request_user.id,
            image="grokai/beer_job:0.0.1",
            name="user_selected_name",
            worker_hostname="valentino-desktop",
            resources=ResourcesModel(generic_resources={"gpu": [0]}),
            expected_duration=180,
        )

        resources_answer: ManagerAnswer = self.manager_service.job(request_user=request_user, job=job)
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=escape_markdown(resources_answer.message, version=2),
            parse_mode="MarkdownV2",
        )

    def resources(self, update: Update, context: CallbackContext):
        request_user: User = update.effective_user

        resources_answer: ManagerAnswer = self.manager_service.list_resources(request_user=request_user)
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=escape_markdown(resources_answer.message, version=2),
            parse_mode="MarkdownV2",
        )

    def run(self):
        dispatcher = self.updater.dispatcher

        dispatcher.add_handler(CommandHandler("job", self.job))
        dispatcher.add_handler(CommandHandler("resources", self.resources))
        dispatcher.add_handler(CommandHandler("set_permission", self.set_permission))
        dispatcher.add_handler(CommandHandler("register_user", self.register_user))
        dispatcher.add_handler(CommandHandler("set_ssh_key", self.set_ssh_key))
        dispatcher.add_handler(CommandHandler("delete_user", self.delete_user))

        self.updater.start_polling()

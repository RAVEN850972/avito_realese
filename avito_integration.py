#!/usr/bin/env python3
"""
Реальная интеграция с Avito API для GPT-ONLY RentalBot
Реализует полноценную работу с Avito Messenger API
"""

import asyncio
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass
import aiohttp
from enum import Enum

from core import RentalBotCore, ClientInfo


class AvitoMessageType(Enum):
    """Типы сообщений Avito"""
    TEXT = "text"
    IMAGE = "image"
    VOICE = "voice"
    CALL = "call"
    LOCATION = "location"
    LINK = "link"
    ITEM = "item"


class AvitoMessageDirection(Enum):
    """Направления сообщений"""
    IN = "in"   # Входящее от клиента
    OUT = "out" # Исходящее от бота


@dataclass
class AvitoMessage:
    """Сообщение в Avito чате"""
    id: str
    chat_id: str
    author_id: int
    content: Dict[str, Any]
    message_type: AvitoMessageType
    direction: AvitoMessageDirection
    created: int
    is_read: bool = False
    
    @property
    def text(self) -> str:
        """Извлекает текст сообщения"""
        if self.message_type == AvitoMessageType.TEXT:
            return self.content.get('text', '')
        return f"[{self.message_type.value}]"
    
    @property
    def datetime(self) -> datetime:
        """Преобразует timestamp в datetime"""
        return datetime.fromtimestamp(self.created)


@dataclass
class AvitoChat:
    """Чат с клиентом на Avito"""
    id: str
    item_id: int
    client_user_id: int
    client_name: str
    last_message: Optional[AvitoMessage]
    created: int
    updated: int
    is_unread: bool = False
    
    @property
    def created_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.created)
    
    @property
    def updated_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.updated)


class AvitoAPIError(Exception):
    """Ошибки Avito API"""
    pass


class AvitoRateLimitError(AvitoAPIError):
    """Превышение лимитов запросов"""
    pass


class AvitoAPIClient:
    """
    Клиент для работы с Avito API
    """
    
    def __init__(self, access_token: str, user_id: int):
        self.access_token = access_token
        self.user_id = user_id
        self.base_url = "https://api.avito.ru"
        self.session: Optional[aiohttp.ClientSession] = None
        self.logger = logging.getLogger(__name__)
        
        # Лимиты запросов
        self.rate_limit_delay = 1.0  # секунд между запросами
        self.last_request_time = 0
        
    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession(
            headers={
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            },
            timeout=aiohttp.ClientTimeout(total=30)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
    
    async def _rate_limit_check(self):
        """Проверка лимитов запросов"""
        current_time = asyncio.get_event_loop().time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.rate_limit_delay:
            wait_time = self.rate_limit_delay - time_since_last
            await asyncio.sleep(wait_time)
        
        self.last_request_time = asyncio.get_event_loop().time()
    
    async def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Выполнение HTTP запроса к Avito API"""
        await self._rate_limit_check()
        
        url = f"{self.base_url}{endpoint}"
        
        try:
            async with self.session.request(method, url, **kwargs) as response:
                response_data = await response.json()
                
                if response.status == 200:
                    return response_data
                elif response.status == 429:
                    raise AvitoRateLimitError("Rate limit exceeded")
                else:
                    error_msg = response_data.get('error', {}).get('message', 'Unknown error')
                    raise AvitoAPIError(f"API Error {response.status}: {error_msg}")
                    
        except aiohttp.ClientError as e:
            raise AvitoAPIError(f"Network error: {e}")
    
    # РАБОТА С ЧАТАМИ
    
    async def get_chats(self, 
                       unread_only: bool = False,
                       item_ids: Optional[List[int]] = None,
                       limit: int = 100,
                       offset: int = 0) -> List[AvitoChat]:
        """Получение списка чатов"""
        
        endpoint = f"/messenger/v2/accounts/{self.user_id}/chats"
        
        params = {
            'limit': limit,
            'offset': offset,
            'unread_only': unread_only
        }
        
        if item_ids:
            params['item_ids'] = ','.join(map(str, item_ids))
        
        response = await self._make_request('GET', endpoint, params=params)
        
        chats = []
        for chat_data in response.get('chats', []):
            chat = self._parse_chat(chat_data)
            chats.append(chat)
        
        return chats
    
    async def get_chat(self, chat_id: str) -> Optional[AvitoChat]:
        """Получение информации о конкретном чате"""
        
        endpoint = f"/messenger/v2/accounts/{self.user_id}/chats/{chat_id}"
        
        try:
            response = await self._make_request('GET', endpoint)
            return self._parse_chat(response)
        except AvitoAPIError:
            return None
    
    def _parse_chat(self, chat_data: Dict[str, Any]) -> AvitoChat:
        """Парсинг данных чата"""
        
        # Извлекаем информацию о клиенте
        users = chat_data.get('users', [])
        client_user = None
        
        for user in users:
            if user['id'] != self.user_id:
                client_user = user
                break
        
        # Парсим последнее сообщение
        last_message = None
        if 'last_message' in chat_data:
            last_message = self._parse_message(
                chat_data['last_message'], 
                chat_data['id']
            )
        
        return AvitoChat(
            id=chat_data['id'],
            item_id=chat_data.get('context', {}).get('value', {}).get('id', 0),
            client_user_id=client_user['id'] if client_user else 0,
            client_name=client_user['name'] if client_user else 'Unknown',
            last_message=last_message,
            created=chat_data['created'],
            updated=chat_data['updated']
        )
    
    # РАБОТА С СООБЩЕНИЯМИ
    
    async def get_messages(self, 
                          chat_id: str,
                          limit: int = 100,
                          offset: int = 0) -> List[AvitoMessage]:
        """Получение сообщений из чата"""
        
        endpoint = f"/messenger/v3/accounts/{self.user_id}/chats/{chat_id}/messages/"
        
        params = {
            'limit': limit,
            'offset': offset
        }
        
        response = await self._make_request('GET', endpoint, params=params)
        
        messages = []
        for msg_data in response:
            message = self._parse_message(msg_data, chat_id)
            messages.append(message)
        
        return messages
    
    def _parse_message(self, msg_data: Dict[str, Any], chat_id: str) -> AvitoMessage:
        """Парсинг сообщения"""
        
        message_type = AvitoMessageType(msg_data.get('type', 'text'))
        direction = AvitoMessageDirection(msg_data.get('direction', 'in'))
        
        return AvitoMessage(
            id=msg_data['id'],
            chat_id=chat_id,
            author_id=msg_data['author_id'],
            content=msg_data.get('content', {}),
            message_type=message_type,
            direction=direction,
            created=msg_data['created'],
            is_read=msg_data.get('is_read', False)
        )
    
    async def send_message(self, chat_id: str, text: str) -> bool:
        """Отправка текстового сообщения"""
        
        endpoint = f"/messenger/v1/accounts/{self.user_id}/chats/{chat_id}/messages"
        
        payload = {
            "message": {
                "text": text
            },
            "type": "text"
        }
        
        try:
            response = await self._make_request('POST', endpoint, json=payload)
            self.logger.info(f"Message sent to chat {chat_id}: {text[:50]}...")
            return True
        except AvitoAPIError as e:
            self.logger.error(f"Failed to send message to {chat_id}: {e}")
            return False
    
    async def mark_chat_read(self, chat_id: str) -> bool:
        """Отметка чата как прочитанного"""
        
        endpoint = f"/messenger/v1/accounts/{self.user_id}/chats/{chat_id}/read"
        
        try:
            await self._make_request('POST', endpoint)
            return True
        except AvitoAPIError as e:
            self.logger.error(f"Failed to mark chat {chat_id} as read: {e}")
            return False


class AvitoGPTBot:
    """
    GPT бот для работы с Avito чатами
    Связывает Avito API с GPT ядром
    """
    
    def __init__(self, 
                 avito_client: AvitoAPIClient,
                 gpt_core: RentalBotCore,
                 telegram_notifier=None):
        self.avito = avito_client
        self.gpt_core = gpt_core
        self.telegram_notifier = telegram_notifier
        self.logger = logging.getLogger(__name__)
        
        # Обработанные сообщения (защита от дублей)
        self.processed_messages: set = set()
        
        # Активные диалоги
        self.active_dialogs: Dict[str, str] = {}  # chat_id -> gpt_user_id
        
        # Статистика
        self.stats = {
            'messages_processed': 0,
            'dialogs_completed': 0,
            'errors': 0,
            'start_time': datetime.now()
        }
        
        # Регистрируем обработчик завершения диалогов
        self.gpt_core.on_completion(self._on_dialog_completion)
    
    async def start_monitoring(self):
        """Запуск мониторинга новых сообщений"""
        self.logger.info("Starting Avito chat monitoring...")
        
        while True:
            try:
                await self._process_new_messages()
                await asyncio.sleep(10)  # Проверяем каждые 10 секунд
                
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                self.stats['errors'] += 1
                await asyncio.sleep(60)  # Увеличиваем интервал при ошибке
    
    async def _process_new_messages(self):
        """Обработка новых сообщений"""
        
        # Получаем непрочитанные чаты
        unread_chats = await self.avito.get_chats(unread_only=True, limit=50)
        
        for chat in unread_chats:
            try:
                await self._process_chat(chat)
            except Exception as e:
                self.logger.error(f"Error processing chat {chat.id}: {e}")
                self.stats['errors'] += 1
    
    async def _process_chat(self, chat: AvitoChat):
        """Обработка сообщений в конкретном чате"""
        
        # Получаем новые сообщения
        messages = await self.avito.get_messages(chat.id, limit=20)
        
        # Сортируем по времени создания
        messages.sort(key=lambda m: m.created)
        
        # Обрабатываем только входящие сообщения от клиента
        for message in messages:
            if (message.direction == AvitoMessageDirection.IN and
                message.id not in self.processed_messages and
                message.message_type == AvitoMessageType.TEXT):
                
                await self._process_client_message(chat, message)
    
    async def _process_client_message(self, chat: AvitoChat, message: AvitoMessage):
        """Обработка сообщения от клиента"""
        
        try:
            # Получаем или создаем ID для GPT диалога
            gpt_user_id = self._get_gpt_user_id(chat)
            
            # Добавляем контекст о квартире для первого сообщения
            client_text = message.text
            if gpt_user_id not in [client.user_id for client in await self.gpt_core.get_all_clients()]:
                # Первое сообщение - добавляем контекст
                client_text = f"[Клиент написал по объявлению квартиры] {client_text}"
            
            # Отправляем в GPT
            gpt_response = await self.gpt_core.chat(gpt_user_id, client_text)
            
            # Отправляем ответ клиенту
            await self.avito.send_message(chat.id, gpt_response.message)
            
            # Отмечаем чат как прочитанный
            await self.avito.mark_chat_read(chat.id)
            
            # Добавляем в обработанные
            self.processed_messages.add(message.id)
            self.stats['messages_processed'] += 1
            
            self.logger.info(f"Processed message from {chat.client_name} in chat {chat.id}")
            
            # Если диалог завершен, уведомляем менеджеров
            if gpt_response.is_completed:
                await self._notify_dialog_completion(chat, gpt_response)
                
        except Exception as e:
            self.logger.error(f"Error processing message {message.id}: {e}")
            self.stats['errors'] += 1
    
    def _get_gpt_user_id(self, chat: AvitoChat) -> str:
        """Получение уникального ID для GPT диалога"""
        gpt_user_id = f"avito_{chat.client_user_id}_{chat.item_id}"
        self.active_dialogs[chat.id] = gpt_user_id
        return gpt_user_id
    
    async def _on_dialog_completion(self, client: ClientInfo):
        """Обработчик завершения диалога"""
        self.stats['dialogs_completed'] += 1
        self.logger.info(f"Dialog completed for GPT user {client.user_id}")
    
    async def _notify_dialog_completion(self, chat: AvitoChat, gpt_response):
        """Уведомление менеджеров о завершенном диалоге"""
        
        if self.telegram_notifier:
            # Формируем данные для отправки менеджеру
            notification_data = {
                'source': 'avito',
                'chat_id': chat.id,
                'client_name': chat.client_name,
                'client_user_id': chat.client_user_id,
                'item_id': chat.item_id,
                'extracted_data': gpt_response.extracted_data,
                'completed_at': datetime.now().isoformat()
            }
            
            await self.telegram_notifier.send_completion_notification(notification_data)
    
    async def get_dialog_history(self, chat_id: str) -> Optional[ClientInfo]:
        """Получение истории диалога"""
        gpt_user_id = self.active_dialogs.get(chat_id)
        if gpt_user_id:
            return await self.gpt_core.get_client_info(gpt_user_id)
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Статистика работы бота"""
        uptime = datetime.now() - self.stats['start_time']
        
        return {
            **self.stats,
            'active_dialogs': len(self.active_dialogs),
            'uptime_hours': uptime.total_seconds() / 3600,
            'processed_messages_per_hour': self.stats['messages_processed'] / max(uptime.total_seconds() / 3600, 1)
        }


class TelegramAvitoNotifier:
    """
    Уведомления в Telegram для менеджеров о завершенных диалогах с Avito
    """
    
    def __init__(self, telegram_bot, manager_chat_ids: List[int]):
        self.telegram_bot = telegram_bot
        self.manager_chat_ids = manager_chat_ids
        self.logger = logging.getLogger(__name__)
    
    async def send_completion_notification(self, data: Dict[str, Any]):
        """Отправка уведомления о завершенном диалоге"""
        
        message = self._format_completion_message(data)
        
        for manager_chat_id in self.manager_chat_ids:
            try:
                await self.telegram_bot.send_message(manager_chat_id, message, parse_mode="HTML")
                self.logger.info(f"Notification sent to manager {manager_chat_id}")
            except Exception as e:
                self.logger.error(f"Failed to send notification to {manager_chat_id}: {e}")
    
    def _format_completion_message(self, data: Dict[str, Any]) -> str:
        """Форматирование сообщения для менеджера"""
        
        extracted = data.get('extracted_data', {})
        
        message = f"""
🎉 <b>НОВАЯ ЗАЯВКА С AVITO!</b>

👤 <b>Клиент:</b> {data.get('client_name', 'Не указано')}
📱 <b>Авито ID:</b> {data.get('client_user_id', 'Не указано')}
🏠 <b>Объявление ID:</b> {data.get('item_id', 'Не указано')}

📋 <b>СОБРАННЫЕ ДАННЫЕ:</b>
👤 <b>Имя:</b> {extracted.get('name', '❌ не указано')}
📱 <b>Телефон:</b> {extracted.get('phone', '❌ не указан')}
🏠 <b>Состав семьи:</b> {extracted.get('residents_info', '❌ не указано')}
👥 <b>Количество жильцов:</b> {extracted.get('residents_count', '❌ не указано')}
👶 <b>Дети:</b> {'✅ есть' if extracted.get('has_children') else '❌ нет' if extracted.get('has_children') is not None else '❓ не указано'}
🐕 <b>Животные:</b> {'✅ есть' if extracted.get('has_pets') else '❌ нет' if extracted.get('has_pets') is not None else '❓ не указано'}
📅 <b>Срок аренды:</b> {extracted.get('rental_period', '❌ не указан')}
🗓️ <b>Дата заезда:</b> {extracted.get('move_in_deadline', '❌ не указана')}

⏰ <b>Завершено:</b> {data.get('completed_at', 'Не указано')[:19]}
🤖 <b>Источник:</b> Avito + GPT-ONLY бот

<i>💬 Чтобы увидеть полный диалог, используйте chat_id: {data.get('chat_id', 'Не указано')}</i>
        """.strip()
        
        return message


# Фабрика для создания полной Avito интеграции
class AvitoIntegrationFactory:
    """Фабрика для создания Avito интеграции"""
    
    @staticmethod
    async def create_full_integration(
        access_token: str,
        user_id: int,
        gpt_core: RentalBotCore,
        telegram_bot=None,
        manager_chat_ids: List[int] = None
    ) -> AvitoGPTBot:
        """Создание полной Avito интеграции"""
        
        # Создаем клиент API
        avito_client = AvitoAPIClient(access_token, user_id)
        
        # Создаем уведомитель для Telegram
        telegram_notifier = None
        if telegram_bot and manager_chat_ids:
            telegram_notifier = TelegramAvitoNotifier(telegram_bot, manager_chat_ids)
        
        # Создаем основной бот
        avito_bot = AvitoGPTBot(avito_client, gpt_core, telegram_notifier)
        
        return avito_bot


# Пример конфигурации и запуска
class AvitoConfig:
    """Конфигурация Avito интеграции"""
    
    def __init__(self):
        self.access_token = ""  # Заполнить реальным токеном
        self.user_id = 0        # Заполнить реальным user_id
        self.manager_chat_ids = []  # ID чатов менеджеров в Telegram
        
        # Настройки мониторинга
        self.polling_interval = 10  # секунд
        self.rate_limit_delay = 1.0  # секунд между запросами
        
        # Настройки обработки
        self.max_messages_per_check = 50
        self.auto_mark_read = True


# Пример использования
async def example_usage():
    """Пример использования Avito интеграции"""
    
    from core import RentalBotCore
    
    # Настройки
    config = AvitoConfig()
    config.access_token = "YOUR_AVITO_ACCESS_TOKEN"
    config.user_id = 12345
    config.manager_chat_ids = [123456789]  # Telegram chat IDs менеджеров
    
    # Создаем GPT ядро
    gpt_core = RentalBotCore("YOUR_OPENAI_KEY")
    
    # Создаем Avito интеграцию
    async with AvitoAPIClient(config.access_token, config.user_id) as avito_client:
        
        # Тест подключения
        chats = await avito_client.get_chats(limit=5)
        print(f"Found {len(chats)} chats")
        
        # Создаем бота
        avito_bot = AvitoGPTBot(avito_client, gpt_core)
        
        # Запускаем мониторинг
        await avito_bot.start_monitoring()


if __name__ == "__main__":
    # Запуск интеграции
    asyncio.run(example_usage())
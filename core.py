#!/usr/bin/env python3
"""
Ядро GPT-ONLY RentalBot - связующий файл всех частей проекта
DSL для управления ботом и интеграциями
"""

import asyncio
import json
import re
import logging
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime
from dataclasses import dataclass
import openai
import aiosqlite

from config import (
    BotConfig, BotPrompts, BotConstants, ErrorMessages,
    get_config, get_required_env_vars
)


@dataclass
class ClientInfo:
    """Информация о клиенте"""
    user_id: str
    raw_data: str = ""
    is_complete: bool = False
    message_count: int = 0
    created_at: datetime = datetime.now()
    final_data: Optional[Dict[str, Any]] = None


@dataclass
class BotResponse:
    """Ответ бота"""
    message: str
    is_completed: bool = False
    extracted_data: Optional[Dict[str, Any]] = None


class RentalBotCore:
    """
    Ядро GPT-ONLY RentalBot
    Управляет всей логикой через GPT без программных шаблонов
    """
    
    def __init__(self, openai_key: str, config: Optional[BotConfig] = None):
        self.openai_client = openai.OpenAI(api_key=openai_key)
        self.config = config or get_config()
        
        # Внутреннее состояние
        self.clients: Dict[str, ClientInfo] = {}
        self.conversation_history: Dict[str, List[Dict]] = {}
        
        # Коллбэки
        self.completion_handlers: List[Callable] = []
        self.message_handlers: List[Callable] = []
        self.error_handlers: List[Callable] = []
        
        # Статистика
        self.stats = {
            'total_clients': 0,
            'completed_clients': 0,
            'total_messages': 0,
            'start_time': datetime.now()
        }
        
        self._initialized = False
        
        if self.config.enable_logging:
            logging.basicConfig(level=logging.INFO)
            self.logger = logging.getLogger(__name__)
        else:
            self.logger = logging.getLogger(__name__)
            self.logger.disabled = True
    
    async def _ensure_initialized(self):
        """Ленивая инициализация"""
        if not self._initialized:
            await self._init_database()
            await self._load_existing_clients()
            self._initialized = True
    
    async def _init_database(self):
        """Инициализация базы данных"""
        async with aiosqlite.connect(self.config.database_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS clients (
                    user_id TEXT PRIMARY KEY,
                    raw_data TEXT,
                    final_data TEXT,
                    is_complete BOOLEAN DEFAULT FALSE,
                    message_count INTEGER DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    timestamp TEXT,
                    sender TEXT,
                    content TEXT
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS integrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id TEXT,
                    integration_type TEXT,
                    data TEXT,
                    status TEXT,
                    created_at TEXT
                )
            """)
            
            await db.commit()
    
    async def _load_existing_clients(self):
        """Загружает существующих клиентов из БД"""
        async with aiosqlite.connect(self.config.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT COUNT(*) as total FROM clients")
            row = await cursor.fetchone()
            self.stats['total_clients'] = row['total']
            
            cursor = await db.execute("SELECT COUNT(*) as completed FROM clients WHERE is_complete = 1")
            row = await cursor.fetchone()
            self.stats['completed_clients'] = row['completed']
            
            cursor = await db.execute("SELECT COUNT(*) as messages FROM messages")
            row = await cursor.fetchone()
            self.stats['total_messages'] = row['messages']
    
    # ОСНОВНЫЕ МЕТОДЫ РАБОТЫ С ДИАЛОГОМ
    
    async def chat(self, user_id: str, message: str) -> BotResponse:
        """
        Главный метод обработки сообщений через GPT
        """
        await self._ensure_initialized()
        
        try:
            # Получаем/создаем клиента
            client = await self._get_or_create_client(user_id)
            was_completed = client.is_complete
            client.message_count += 1
            self.stats['total_messages'] += 1
            
            # Сохраняем сообщение пользователя
            await self._save_message(user_id, "user", message)
            
            # Добавляем в сырые данные
            client.raw_data += f"\nПользователь: {message}"
            
            # Обновляем историю разговора
            await self._update_conversation_history(user_id, "user", message)
            
            # Генерируем ответ через GPT
            bot_message = await self._generate_gpt_response(client)
            
            # Проверяем завершенность диалога
            is_completed = BotConstants.COMPLETION_MARKER in bot_message
            if is_completed:
                bot_message = bot_message.replace(BotConstants.COMPLETION_MARKER, "").strip()
                client.is_complete = True
                self.stats['completed_clients'] += 1
                
                # Извлекаем финальные данные
                client.final_data = await self._extract_final_data(client)
            
            # Сохраняем ответ бота
            client.raw_data += f"\nСветлана: {bot_message}"
            await self._update_conversation_history(user_id, "assistant", bot_message)
            await self._save_message(user_id, "bot", bot_message)
            await self._save_client(client)
            
            # Создаем ответ
            response = BotResponse(
                message=bot_message,
                is_completed=is_completed,
                extracted_data=client.final_data if is_completed else None
            )
            
            # Вызываем коллбэки
            await self._call_handlers(user_id, message, response, client, was_completed)
            
            return response
            
        except Exception as e:
            self.logger.error(f"Ошибка в чате для {user_id}: {e}")
            await self._call_error_handlers(user_id, message, e)
            return BotResponse(message=ErrorMessages.TECHNICAL_ERROR)
    
    async def _generate_gpt_response(self, client: ClientInfo) -> str:
        """Генерирует ответ через GPT"""
        try:
            # Строим контекст
            messages = [{"role": "system", "content": BotPrompts.SYSTEM_PROMPT}]
            
            # Добавляем историю диалога
            conversation = self.conversation_history.get(client.user_id, [])
            messages.extend(conversation)
            
            # Если это первое сообщение - добавляем специальную инструкцию
            if client.message_count == 1:
                messages.append({
                    "role": "system", 
                    "content": BotPrompts.FIRST_MESSAGE_INSTRUCTION
                })
            
            response = self.openai_client.chat.completions.create(
                model=self.config.openai_model,
                messages=messages,
                temperature=self.config.openai_temperature,
                max_tokens=self.config.openai_max_tokens
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            self.logger.error(f"Ошибка OpenAI: {e}")
            return ErrorMessages.OPENAI_ERROR
    
    async def _extract_final_data(self, client: ClientInfo) -> Dict[str, Any]:
        """Извлекает финальные структурированные данные через GPT"""
        try:
            extraction_prompt = BotPrompts.EXTRACTION_PROMPT_TEMPLATE.format(
                dialog_history=client.raw_data
            )
            
            response = self.openai_client.chat.completions.create(
                model=self.config.openai_model,
                messages=[{"role": "user", "content": extraction_prompt}],
                temperature=0.1,
                max_tokens=400
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Извлекаем JSON
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                extracted = json.loads(json_match.group())
                self.logger.info(f"Финальные данные извлечены для {client.user_id}")
                return extracted
                
        except Exception as e:
            self.logger.error(f"Ошибка извлечения данных: {e}")
        
        return {}
    
    # МЕТОДЫ РАБОТЫ С КЛИЕНТАМИ
    
    async def _get_or_create_client(self, user_id: str) -> ClientInfo:
        """Получает или создает клиента"""
        if user_id in self.clients:
            return self.clients[user_id]
        
        async with aiosqlite.connect(self.config.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM clients WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            
            if row:
                final_data = None
                if row['final_data']:
                    try:
                        final_data = json.loads(row['final_data'])
                    except:
                        pass
                
                client = ClientInfo(
                    user_id=user_id,
                    raw_data=row['raw_data'] or "",
                    is_complete=bool(row['is_complete']),
                    message_count=row['message_count'] or 0,
                    final_data=final_data
                )
            else:
                client = ClientInfo(user_id=user_id)
                self.stats['total_clients'] += 1
            
            self.clients[user_id] = client
            return client
    
    async def get_client_info(self, user_id: str) -> ClientInfo:
        """Возвращает информацию о клиенте"""
        return await self._get_or_create_client(user_id)
    
    async def get_all_clients(self) -> List[ClientInfo]:
        """Возвращает всех клиентов"""
        async with aiosqlite.connect(self.config.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT user_id FROM clients")
            rows = await cursor.fetchall()
            
            clients = []
            for row in rows:
                client = await self._get_or_create_client(row['user_id'])
                clients.append(client)
            
            return clients
    
    async def reset_client(self, user_id: str) -> bool:
        """Сбрасывает данные клиента"""
        try:
            await self._ensure_initialized()
            
            self.clients[user_id] = ClientInfo(user_id=user_id)
            await self._save_client(self.clients[user_id])
            
            # Очищаем историю разговора
            if user_id in self.conversation_history:
                del self.conversation_history[user_id]
            
            return True
        except Exception as e:
            self.logger.error(f"Ошибка сброса клиента {user_id}: {e}")
            return False
    
    # МЕТОДЫ РАБОТЫ С ИСТОРИЕЙ И БАЗОЙ ДАННЫХ
    
    async def _update_conversation_history(self, user_id: str, role: str, content: str):
        """Обновляет историю разговора"""
        if user_id not in self.conversation_history:
            self.conversation_history[user_id] = []
        
        self.conversation_history[user_id].append({
            "role": role,
            "content": content
        })
        
        # Ограничиваем размер истории
        if len(self.conversation_history[user_id]) > self.config.max_conversation_history:
            self.conversation_history[user_id] = self.conversation_history[user_id][-self.config.max_conversation_history:]
    
    async def _save_client(self, client: ClientInfo):
        """Сохраняет клиента в БД"""
        final_data_json = json.dumps(client.final_data) if client.final_data else None
        
        async with aiosqlite.connect(self.config.database_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO clients 
                (user_id, raw_data, final_data, is_complete, message_count, 
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                client.user_id, client.raw_data, final_data_json, client.is_complete,
                client.message_count, client.created_at.isoformat(), 
                datetime.now().isoformat()
            ))
            await db.commit()
    
    async def _save_message(self, user_id: str, sender: str, content: str):
        """Сохраняет сообщение в БД"""
        async with aiosqlite.connect(self.config.database_path) as db:
            await db.execute("""
                INSERT INTO messages (user_id, timestamp, sender, content)
                VALUES (?, ?, ?, ?)
            """, (user_id, datetime.now().isoformat(), sender, content))
            await db.commit()
    
    # МЕТОДЫ РАБОТЫ С КОЛЛБЭКАМИ
    
    async def _call_handlers(self, user_id: str, message: str, response: BotResponse,
                           client: ClientInfo, was_completed: bool):
        """Вызывает все зарегистрированные обработчики"""
        
        # Обработчики сообщений
        for handler in self.message_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(user_id, message, response)
                else:
                    handler(user_id, message, response)
            except Exception as e:
                self.logger.error(f"Ошибка message handler: {e}")
        
        # Обработчики завершения
        if response.is_completed and not was_completed:
            for handler in self.completion_handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(client)
                    else:
                        handler(client)
                except Exception as e:
                    self.logger.error(f"Ошибка completion handler: {e}")
    
    async def _call_error_handlers(self, user_id: str, message: str, error: Exception):
        """Вызывает обработчики ошибок"""
        for handler in self.error_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(user_id, message, error)
                else:
                    handler(user_id, message, error)
            except Exception as e:
                self.logger.error(f"Ошибка error handler: {e}")
    
    # ПУБЛИЧНЫЕ МЕТОДЫ ДЛЯ РЕГИСТРАЦИИ ОБРАБОТЧИКОВ
    
    def on_completion(self, handler: Callable):
        """Регистрирует обработчик завершения диалога"""
        self.completion_handlers.append(handler)
        return self
    
    def on_message(self, handler: Callable):
        """Регистрирует обработчик сообщений"""
        self.message_handlers.append(handler)
        return self
    
    def on_error(self, handler: Callable):
        """Регистрирует обработчик ошибок"""
        self.error_handlers.append(handler)
        return self
    
    # ИНТЕГРАЦИИ И РАСШИРЕНИЯ
    
    async def register_integration(self, client_id: str, integration_type: str, 
                                 data: Dict[str, Any], status: str = "pending"):
        """Регистрирует интеграцию для клиента (например, с Авито)"""
        await self._ensure_initialized()
        
        async with aiosqlite.connect(self.config.database_path) as db:
            await db.execute("""
                INSERT INTO integrations (client_id, integration_type, data, status, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (client_id, integration_type, json.dumps(data), status, datetime.now().isoformat()))
            await db.commit()
    
    async def get_integrations(self, client_id: str, integration_type: Optional[str] = None) -> List[Dict]:
        """Получает интеграции для клиента"""
        await self._ensure_initialized()
        
        async with aiosqlite.connect(self.config.database_path) as db:
            db.row_factory = aiosqlite.Row
            
            if integration_type:
                cursor = await db.execute(
                    "SELECT * FROM integrations WHERE client_id = ? AND integration_type = ?",
                    (client_id, integration_type)
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM integrations WHERE client_id = ?",
                    (client_id,)
                )
            
            rows = await cursor.fetchall()
            
            integrations = []
            for row in rows:
                integration = {
                    'id': row['id'],
                    'client_id': row['client_id'],
                    'integration_type': row['integration_type'],
                    'data': json.loads(row['data']) if row['data'] else {},
                    'status': row['status'],
                    'created_at': row['created_at']
                }
                integrations.append(integration)
            
            return integrations
    
    async def update_integration_status(self, integration_id: int, status: str):
        """Обновляет статус интеграции"""
        await self._ensure_initialized()
        
        async with aiosqlite.connect(self.config.database_path) as db:
            await db.execute(
                "UPDATE integrations SET status = ? WHERE id = ?",
                (status, integration_id)
            )
            await db.commit()
    
    # СИСТЕМА МОНИТОРИНГА И ЗДОРОВЬЯ
    
    async def health_check(self) -> Dict[str, Any]:
        """Проверка состояния системы"""
        try:
            await self._ensure_initialized()
            
            uptime = datetime.now() - self.stats['start_time']
            
            return {
                'status': 'healthy',
                'mode': 'GPT-only-modular',
                'initialized': self._initialized,
                'uptime_hours': uptime.total_seconds() / 3600,
                'stats': self.stats.copy(),
                'config': {
                    'model': self.config.openai_model,
                    'temperature': self.config.openai_temperature,
                    'max_tokens': self.config.openai_max_tokens,
                    'database_path': self.config.database_path
                },
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def get_stats(self) -> Dict[str, Any]:
        """Возвращает статистику бота"""
        uptime = datetime.now() - self.stats['start_time']
        
        return {
            'users_count': self.stats['total_clients'],
            'messages_count': self.stats['total_messages'],
            'completions_count': self.stats['completed_clients'],
            'uptime_hours': uptime.total_seconds() / 3600,
            'start_time': self.stats['start_time'].isoformat(),
            'active_conversations': len(self.conversation_history)
        }
    
    # УТИЛИТЫ ДЛЯ ФОРМАТИРОВАНИЯ ДАННЫХ
    
    def format_client_data(self, client: ClientInfo) -> Dict[str, str]:
        """Форматирует данные клиента для отображения"""
        if not client.final_data:
            return {
                'message_count': str(client.message_count),
                'status': 'В процессе',
                'dialog_preview': client.raw_data[:BotConstants.MAX_DIALOG_PREVIEW_LENGTH] + "..." 
                                 if len(client.raw_data) > BotConstants.MAX_DIALOG_PREVIEW_LENGTH 
                                 else client.raw_data
            }
        
        return {
            'name': client.final_data.get('name') or '❌ не указано',
            'phone': client.final_data.get('phone') or '❌ не указан',
            'residents_info': client.final_data.get('residents_info') or '❌ не указано',
            'children_status': '✅ есть' if client.final_data.get('has_children') else 
                              '❌ нет' if client.final_data.get('has_children') is not None else '❓ не указано',
            'pets_status': '✅ есть' if client.final_data.get('has_pets') else 
                          '❌ нет' if client.final_data.get('has_pets') is not None else '❓ не указано',
            'rental_period': client.final_data.get('rental_period') or '❌ не указан',
            'move_in_deadline': client.final_data.get('move_in_deadline') or '❌ не указана',
            'message_count': str(client.message_count),
            'status': '✅ Завершена'
        }


class RentalBotFactory:
    """Фабрика для создания экземпляров бота с различными конфигурациями"""
    
    @staticmethod
    def create_production_bot(openai_key: str) -> RentalBotCore:
        """Создает бота для продакшена"""
        config = get_config()
        config.enable_logging = True
        config.enable_stats = True
        return RentalBotCore(openai_key, config)
    
    @staticmethod
    def create_development_bot(openai_key: str) -> RentalBotCore:
        """Создает бота для разработки"""
        config = get_config()
        config.database_path = "dev_gpt_rental.db"
        config.enable_logging = True
        config.openai_temperature = 0.9  # Более креативные ответы для тестов
        return RentalBotCore(openai_key, config)
    
    @staticmethod
    def create_test_bot(openai_key: str) -> RentalBotCore:
        """Создает бота для тестирования"""
        config = get_config()
        config.database_path = ":memory:"  # В памяти
        config.enable_logging = False
        config.enable_stats = False
        return RentalBotCore(openai_key, config)


# DSL для удобной настройки бота
class BotBuilder:
    """Строитель бота с fluent interface"""
    
    def __init__(self, openai_key: str):
        self.openai_key = openai_key
        self.config = get_config()
        self._completion_handlers = []
        self._message_handlers = []
        self._error_handlers = []
    
    def with_database(self, path: str):
        """Устанавливает путь к базе данных"""
        self.config.database_path = path
        return self
    
    def with_model(self, model: str):
        """Устанавливает модель OpenAI"""
        self.config.openai_model = model
        return self
    
    def with_temperature(self, temperature: float):
        """Устанавливает температуру для GPT"""
        self.config.openai_temperature = temperature
        return self
    
    def with_max_tokens(self, max_tokens: int):
        """Устанавливает максимальное количество токенов"""
        self.config.openai_max_tokens = max_tokens
        return self
    
    def with_completion_handler(self, handler: Callable):
        """Добавляет обработчик завершения диалога"""
        self._completion_handlers.append(handler)
        return self
    
    def with_message_handler(self, handler: Callable):
        """Добавляет обработчик сообщений"""
        self._message_handlers.append(handler)
        return self
    
    def with_error_handler(self, handler: Callable):
        """Добавляет обработчик ошибок"""
        self._error_handlers.append(handler)
        return self
    
    def enable_logging(self, enabled: bool = True):
        """Включает/выключает логирование"""
        self.config.enable_logging = enabled
        return self
    
    def enable_stats(self, enabled: bool = True):
        """Включает/выключает сбор статистики"""
        self.config.enable_stats = enabled
        return self
    
    def build(self) -> RentalBotCore:
        """Создает экземпляр бота"""
        bot = RentalBotCore(self.openai_key, self.config)
        
        # Регистрируем обработчики
        for handler in self._completion_handlers:
            bot.on_completion(handler)
        
        for handler in self._message_handlers:
            bot.on_message(handler)
        
        for handler in self._error_handlers:
            bot.on_error(handler)
        
        return bot


# Примеры использования DSL
def create_bot_with_monitoring(openai_key: str) -> RentalBotCore:
    """Создает бота с мониторингом"""
    
    def log_completion(client: ClientInfo):
        print(f"✅ Завершен диалог с клиентом {client.user_id}")
        if client.final_data:
            print(f"📱 Телефон: {client.final_data.get('phone')}")
    
    def log_errors(user_id: str, message: str, error: Exception):
        print(f"❌ Ошибка для {user_id}: {error}")
    
    return (BotBuilder(openai_key)
            .with_completion_handler(log_completion)
            .with_error_handler(log_errors)
            .enable_logging(True)
            .enable_stats(True)
            .build())


def create_high_performance_bot(openai_key: str) -> RentalBotCore:
    """Создает бота для высокой производительности"""
    
    return (BotBuilder(openai_key)
            .with_model("gpt-4o-mini")
            .with_temperature(0.7)
            .with_max_tokens(250)
            .with_database("production_rental.db")
            .enable_stats(False)  # Отключаем для производительности
            .build())
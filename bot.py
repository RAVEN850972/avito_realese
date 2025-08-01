#!/usr/bin/env python3
"""
Telegram бот для тестирования GPT-ONLY RentalBot в реальном времени
Позволяет полноценно протестировать диалоговую систему через Telegram
"""

import asyncio
import logging
import os
import sys
import time
from datetime import datetime
from typing import Optional, Dict, Any

# Добавляем путь к проекту
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("💡 Рекомендуется установить python-dotenv: pip install python-dotenv")

try:
    from aiogram import Bot, Dispatcher, types, F
    from aiogram.filters import Command, CommandStart
    from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.state import State, StatesGroup
    from aiogram.fsm.storage.memory import MemoryStorage
except ImportError:
    print("❌ Не установлена библиотека aiogram")
    print("💡 Установите: pip install aiogram>=3.0.0")
    exit(1)

# Импорты проекта
from core import RentalBotCore, BotBuilder, ClientInfo
from config import get_required_env_vars, BotConfig


class TestStates(StatesGroup):
    """Состояния для FSM"""
    TESTING = State()
    MENU = State()


class TelegramTestBot:
    """
    Telegram бот для тестирования диалоговой системы GPT-ONLY RentalBot
    """
    
    def __init__(self, telegram_token: str, openai_key: str):
        self.telegram_token = telegram_token
        self.openai_key = openai_key
        
        # Создаем GPT ядро для тестирования
        self.rental_bot = self._create_test_rental_bot()
        
        # Telegram компоненты
        self.bot = Bot(token=telegram_token)
        self.storage = MemoryStorage()
        self.dp = Dispatcher(storage=self.storage)
        
        # Статистика тестирования
        self.test_stats = {
            'total_testers': 0,
            'total_test_messages': 0,
            'completed_tests': 0,
            'reset_count': 0,
            'start_time': datetime.now()
        }
        
        # Активные тестеры
        self.active_testers: Dict[int, Dict] = {}
        
        # Настройка логирования
        self.logger = self._setup_logging()
        
        # Регистрируем обработчики
        self._register_handlers()
        
        # Регистрируем коллбэки для GPT ядра
        self._setup_gpt_callbacks()
        
        print("🧪 Telegram Test Bot для GPT-ONLY RentalBot initialized")
    
    def _setup_logging(self) -> logging.Logger:
        """Настройка логирования"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - TestBot - %(levelname)s - %(message)s'
        )
        return logging.getLogger(__name__)
    
    def _create_test_rental_bot(self) -> RentalBotCore:
        """Создание тестового GPT ядра"""
        return (BotBuilder(self.openai_key)
                .with_database("test_rental.db")
                .with_temperature(0.8)
                .with_max_tokens(300)
                .enable_logging(True)
                .enable_stats(True)
                .build())
    
    def _setup_gpt_callbacks(self):
        """Настройка коллбэков для GPT ядра"""
        
        def on_completion_handler(client: ClientInfo):
            """Обработчик завершения диалога"""
            self.test_stats['completed_tests'] += 1
            self.logger.info(f"Test completion for {client.user_id}")
        
        def on_error_handler(user_id: str, message: str, error: Exception):
            """Обработчик ошибок GPT"""
            self.logger.error(f"GPT error for {user_id}: {error}")
        
        self.rental_bot.on_completion(on_completion_handler)
        self.rental_bot.on_error(on_error_handler)
    
    def _register_handlers(self):
        """Регистрация обработчиков Telegram"""
        
        # Команды
        self.dp.message(CommandStart())(self.cmd_start)
        self.dp.message(Command("reset"))(self.cmd_reset)
        self.dp.message(Command("stats"))(self.cmd_stats)
        self.dp.message(Command("info"))(self.cmd_info)
        self.dp.message(Command("help"))(self.cmd_help)
        self.dp.message(Command("debug"))(self.cmd_debug)
        
        # Inline кнопки
        self.dp.callback_query(F.data == "start_test")(self.btn_start_test)
        self.dp.callback_query(F.data == "reset_dialog")(self.btn_reset_dialog)
        self.dp.callback_query(F.data == "show_info")(self.btn_show_info)
        self.dp.callback_query(F.data == "show_stats")(self.btn_show_stats)
        self.dp.callback_query(F.data == "system_health")(self.btn_system_health)
        self.dp.callback_query(F.data == "back_to_menu")(self.btn_back_to_menu)
        self.dp.callback_query(F.data == "confirm_reset")(self.btn_confirm_reset)
        self.dp.callback_query(F.data == "cancel_reset")(self.btn_cancel_reset)
        
        # Обработка тестовых сообщений
        self.dp.message(F.text, TestStates.TESTING)(self.handle_test_message)
        self.dp.message(F.text)(self.handle_menu_message)
    
    # КОМАНДЫ
    
    async def cmd_start(self, message: Message, state: FSMContext):
        """Команда /start"""
        user_id = message.from_user.id
        user_name = message.from_user.first_name or "Тестировщик"
        
        # Регистрируем тестера
        if user_id not in self.active_testers:
            self.active_testers[user_id] = {
                'name': user_name,
                'start_time': datetime.now(),
                'messages_sent': 0,
                'resets_count': 0,
                'last_activity': datetime.now()
            }
            self.test_stats['total_testers'] += 1
        
        await state.set_state(TestStates.MENU)
        
        welcome_text = f"""
👋 <b>Добро пожаловать, {user_name}!</b>

🧪 <b>GPT-ONLY RentalBot - Тестовая среда</b>

Этот бот позволяет протестировать диалоговую систему в реальном времени.
Вы можете общаться с GPT как с настоящим агентом по недвижимости!

<b>🎯 Что тестируем:</b>
• Естественное общение с GPT
• Сбор информации о клиенте
• Понимание контекста и нюансов
• Качество извлечения данных
• Завершение диалога

<b>⚡ Особенности тестирования:</b>
• Полная изоляция вашего диалога
• Возможность сброса и повторного тестирования
• Детальная статистика и отладка
• Реальные промпты как в продакшене

<b>🔄 Управление:</b>
/reset - сбросить диалог
/stats - статистика тестирования
/info - информация о текущем диалоге
/help - справка

<i>🤖 Система работает через GPT-4o-mini</i>
        """
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🧪 Начать тестирование", callback_data="start_test")
            ],
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data="show_stats"),
                InlineKeyboardButton(text="📋 Мой диалог", callback_data="show_info")
            ],
            [
                InlineKeyboardButton(text="⚙️ Здоровье системы", callback_data="system_health")
            ]
        ])
        
        await message.answer(welcome_text, reply_markup=keyboard, parse_mode="HTML")
        self.logger.info(f"New tester: {user_name} ({user_id})")
    
    async def cmd_reset(self, message: Message, state: FSMContext):
        """Команда /reset"""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, сбросить", callback_data="confirm_reset"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_reset")
            ]
        ])
        
        await message.answer(
            "🔄 <b>Сброс диалога</b>\n\n"
            "Вы уверены, что хотите сбросить текущий диалог?\n"
            "Вся история общения будет удалена и вы сможете начать заново.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    
    async def cmd_stats(self, message: Message, state: FSMContext):
        """Команда /stats"""
        await self._show_stats(message)
    
    async def cmd_info(self, message: Message, state: FSMContext):
        """Команда /info"""
        await self._show_user_info(message)
    
    async def cmd_help(self, message: Message, state: FSMContext):
        """Команда /help"""
        help_text = """
📖 <b>СПРАВКА ПО ТЕСТИРОВАНИЮ</b>

<b>🎯 Цель тестирования:</b>
Протестировать GPT-ONLY систему для сбора заявок на аренду квартир.

<b>🧪 Как тестировать:</b>
1. Нажмите "Начать тестирование"
2. Общайтесь как реальный клиент
3. GPT будет собирать информацию о вас
4. Попробуйте разные сценарии общения

<b>📋 Что должен собрать GPT:</b>
• Состав семьи (пол, возраст каждого)
• Наличие детей и животных
• Ваше имя
• Срок аренды
• Дата заезда  
• Номер телефона

<b>💬 Примеры сообщений:</b>
• "Привет, интересует квартира"
• "Нас двое - я 25 лет и девушка 23 года"
• "Детей нет, но есть кот"
• "Меня зовут Александр"
• "Хотим снять на год"
• "Заехать нужно до 15 числа"
• "+79123456789"

<b>🔬 Тестовые сценарии:</b>
• Обычный клиент без особенностей
• Семья с детьми
• Клиент с животными
• Срочный переезд
• Вопросы о квартире
• Нечеткие ответы

<b>⚡ Команды:</b>
/reset - сбросить диалог
/stats - статистика
/info - текущий диалог
/debug - отладочная информация

<b>🎨 Особенности GPT-ONLY:</b>
✅ Живое естественное общение
✅ Понимание контекста
✅ Адаптивные ответы
✅ Умная обработка нюансов
✅ Автоматическое извлечение данных

<i>🧠 Вся логика управляется искусственным интеллектом!</i>
        """
        
        await message.answer(help_text, parse_mode="HTML")
    
    async def cmd_debug(self, message: Message, state: FSMContext):
        """Команда /debug - отладочная информация"""
        user_id = str(message.from_user.id)
        
        try:
            # Получаем информацию о клиенте из GPT ядра
            client = await self.rental_bot.get_client_info(user_id)
            
            debug_text = f"""
🐛 <b>ОТЛАДОЧНАЯ ИНФОРМАЦИЯ</b>

<b>👤 Пользователь:</b>
• ID: <code>{user_id}</code>
• Сообщений: {client.message_count}
• Создан: {client.created_at.strftime('%d.%m.%Y %H:%M')}
• Завершен: {'✅ Да' if client.is_complete else '❌ Нет'}

<b>💾 Сырые данные:</b>
<code>{client.raw_data[:500] if client.raw_data else 'Пусто'}{'...' if len(client.raw_data or '') > 500 else ''}</code>

<b>📊 Финальные данные:</b>
{self._format_final_data(client.final_data) if client.final_data else '❌ Еще не извлечены'}

<b>⚙️ Система:</b>
• Модель: {self.rental_bot.config.openai_model}
• Температура: {self.rental_bot.config.openai_temperature}
• Макс токенов: {self.rental_bot.config.openai_max_tokens}
            """
            
            await message.answer(debug_text, parse_mode="HTML")
            
        except Exception as e:
            await message.answer(f"❌ Ошибка получения отладочной информации: {e}")
    
    # ОБРАБОТЧИКИ КНОПОК
    
    async def btn_start_test(self, callback: CallbackQuery, state: FSMContext):
        """Начать тестирование"""
        await state.set_state(TestStates.TESTING)
        
        test_text = """
🧪 <b>ТЕСТИРОВАНИЕ ЗАПУЩЕНО!</b>

Теперь просто общайтесь как обычный клиент, который ищет квартиру в аренду.
GPT будет отвечать вам как агент по недвижимости Светлана.

<b>💡 Советы для тестирования:</b>
• Пишите естественно, как в жизни
• Попробуйте задать вопросы о квартире
• Дайте нечеткие ответы на некоторые вопросы
• Посмотрите как GPT уточняет детали

<b>🎯 Цель:</b> GPT должен собрать всю информацию и завершить диалог фразой с [COMPLETE]

<i>💬 Начните с любого сообщения, например: "Привет, интересует квартира"</i>

/reset - сбросить диалог в любой момент
        """
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Сбросить диалог", callback_data="reset_dialog")],
            [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")]
        ])
        
        await callback.message.edit_text(test_text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer("Тестирование началось! Пишите сообщения.")
    
    async def btn_reset_dialog(self, callback: CallbackQuery, state: FSMContext):
        """Кнопка сброса диалога"""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, сбросить", callback_data="confirm_reset"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_reset")
            ]
        ])
        
        await callback.message.edit_text(
            "🔄 <b>Подтверждение сброса</b>\n\n"
            "Вы уверены, что хотите сбросить диалог?\n"
            "Вся история будет удалена.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer()
    
    async def btn_confirm_reset(self, callback: CallbackQuery, state: FSMContext):
        """Подтверждение сброса"""
        user_id = str(callback.from_user.id)
        
        try:
            # Сбрасываем в GPT ядре
            success = await self.rental_bot.reset_client(user_id)
            
            if success:
                # Обновляем статистику
                if callback.from_user.id in self.active_testers:
                    self.active_testers[callback.from_user.id]['resets_count'] += 1
                self.test_stats['reset_count'] += 1
                
                await state.set_state(TestStates.MENU)
                
                success_text = """
✅ <b>Диалог успешно сброшен!</b>

Теперь вы можете начать тестирование заново.
GPT забыл всю предыдущую историю общения.

Готовы к новому тесту?
                """
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🧪 Начать новый тест", callback_data="start_test")],
                    [InlineKeyboardButton(text="📊 Статистика", callback_data="show_stats")]
                ])
                
                await callback.message.edit_text(success_text, reply_markup=keyboard, parse_mode="HTML")
                await callback.answer("Диалог сброшен!")
                
                self.logger.info(f"Dialog reset for user {user_id}")
                
            else:
                await callback.answer("❌ Ошибка сброса диалога", show_alert=True)
                
        except Exception as e:
            await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
    
    async def btn_cancel_reset(self, callback: CallbackQuery, state: FSMContext):
        """Отмена сброса"""
        current_state = await state.get_state()
        
        if current_state == TestStates.TESTING:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Сбросить диалог", callback_data="reset_dialog")],
                [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")]
            ])
            
            await callback.message.edit_text(
                "🧪 <b>Тестирование продолжается</b>\n\n"
                "Продолжайте общение с GPT ботом.\n"
                "Пишите сообщения для тестирования диалоговой системы.",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            await self.cmd_start(callback.message, state)
        
        await callback.answer("Сброс отменен")
    
    async def btn_show_info(self, callback: CallbackQuery, state: FSMContext):
        """Показать информацию о диалоге"""
        await self._show_user_info(callback.message, edit=True)
        await callback.answer()
    
    async def btn_show_stats(self, callback: CallbackQuery, state: FSMContext):
        """Показать статистику"""
        await self._show_stats(callback.message, edit=True)
        await callback.answer()
    
    async def btn_system_health(self, callback: CallbackQuery, state: FSMContext):
        """Здоровье системы"""
        try:
            health = await self.rental_bot.health_check()
            
            status_icon = "✅" if health['status'] == 'healthy' else "❌"
            
            health_text = f"""
⚙️ <b>ЗДОРОВЬЕ СИСТЕМЫ</b>

{status_icon} <b>Статус:</b> {health['status']}
⏰ <b>Время работы:</b> {health.get('uptime_hours', 0):.1f} часов

<b>🧠 GPT Ядро:</b>
👥 Клиентов: {health.get('stats', {}).get('total_clients', 0)}
✅ Завершено: {health.get('stats', {}).get('completed_clients', 0)}
💬 Сообщений: {health.get('stats', {}).get('total_messages', 0)}

<b>🔧 Конфигурация:</b>
🤖 Модель: {health.get('config', {}).get('model', 'unknown')}
🌡️ Температура: {health.get('config', {}).get('temperature', 0)}
🎯 Токенов: {health.get('config', {}).get('max_tokens', 0)}

<b>🧪 Тестирование:</b>
👥 Тестеров: {self.test_stats['total_testers']}
💬 Тест сообщений: {self.test_stats['total_test_messages']}
✅ Завершенных тестов: {self.test_stats['completed_tests']}
🔄 Сбросов: {self.test_stats['reset_count']}

<i>Проверено: {datetime.now().strftime('%H:%M:%S')}</i>
            """
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Обновить", callback_data="system_health")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
            ])
            
            await callback.message.edit_text(health_text, reply_markup=keyboard, parse_mode="HTML")
            
        except Exception as e:
            await callback.answer(f"❌ Ошибка проверки системы: {e}", show_alert=True)
    
    async def btn_back_to_menu(self, callback: CallbackQuery, state: FSMContext):
        """Возврат в меню"""
        await state.set_state(TestStates.MENU)
        await self.cmd_start(callback.message, state)
        await callback.answer()
    
    # ОБРАБОТКА СООБЩЕНИЙ
    
    async def handle_test_message(self, message: Message, state: FSMContext):
        """Обработка тестовых сообщений в режиме тестирования"""
        user_id = str(message.from_user.id)
        text = message.text
        
        # Обновляем статистику
        if message.from_user.id in self.active_testers:
            self.active_testers[message.from_user.id]['messages_sent'] += 1
            self.active_testers[message.from_user.id]['last_activity'] = datetime.now()
        
        self.test_stats['total_test_messages'] += 1
        
        try:
            # Показываем typing
            await self.bot.send_chat_action(message.chat.id, "typing")
            
            start_time = time.time()
            
            # Отправляем в GPT ядро
            response = await self.rental_bot.chat(user_id, text)
            
            response_time = time.time() - start_time
            
            # Форматируем ответ
            bot_message = response.message
            
            # Добавляем индикатор завершения
            if response.is_completed:
                bot_message += "\n\n🎉 <b>ТЕСТ ЗАВЕРШЕН!</b>"
                
                if response.extracted_data:
                    bot_message += "\n\n📋 <b>Извлеченные данные:</b>"
                    bot_message += f"\n{self._format_extracted_data(response.extracted_data)}"
                
                # Кнопки после завершения
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Новый тест", callback_data="confirm_reset")],
                    [InlineKeyboardButton(text="📊 Статистика", callback_data="show_stats")],
                    [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")]
                ])
                
                await message.answer(bot_message, reply_markup=keyboard, parse_mode="HTML")
                
                # Возвращаем в меню
                await state.set_state(TestStates.MENU)
                
            else:
                # Обычный ответ с кнопками управления
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Сбросить", callback_data="reset_dialog")],
                    [InlineKeyboardButton(text="📋 Мой диалог", callback_data="show_info")]
                ])
                
                await message.answer(bot_message, reply_markup=keyboard, parse_mode="HTML")
            
            # Логируем
            self.logger.info(f"Test message processed for {user_id} in {response_time:.2f}s")
            
        except Exception as e:
            error_text = f"❌ <b>Ошибка тестирования:</b>\n<code>{str(e)}</code>\n\nПопробуйте еще раз или сбросьте диалог."
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Сбросить диалог", callback_data="reset_dialog")],
                [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")]
            ])
            
            await message.answer(error_text, reply_markup=keyboard, parse_mode="HTML")
            self.logger.error(f"Test error for {user_id}: {e}")
    
    async def handle_menu_message(self, message: Message, state: FSMContext):
        """Обработка сообщений в режиме меню"""
        help_text = """
📱 <b>Используйте кнопки или команды:</b>

🧪 /start - главное меню
🔄 /reset - сбросить диалог  
📊 /stats - статистика
📋 /info - мой диалог
❓ /help - справка
🐛 /debug - отладка

Чтобы начать тестирование, нажмите кнопку "Начать тестирование" или используйте /start
        """
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧪 Начать тестирование", callback_data="start_test")]
        ])
        
        await message.answer(help_text, reply_markup=keyboard, parse_mode="HTML")
    
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    
    async def _show_stats(self, message: Message, edit: bool = False):
        """Показать статистику тестирования"""
        uptime = datetime.now() - self.test_stats['start_time']
        
        # Статистика GPT ядра
        gpt_stats = self.rental_bot.get_stats()
        
        stats_text = f"""
📊 <b>СТАТИСТИКА ТЕСТИРОВАНИЯ</b>

<b>🧪 Тестовая среда:</b>
👥 Тестировщиков: {self.test_stats['total_testers']}
💬 Тест сообщений: {self.test_stats['total_test_messages']}
✅ Завершенных тестов: {self.test_stats['completed_tests']}
🔄 Сбросов диалогов: {self.test_stats['reset_count']}
⏰ Время работы: {uptime.days}д {uptime.seconds//3600}ч

<b>🧠 GPT Ядро:</b>
👥 Всего клиентов: {gpt_stats['users_count']}
💬 Всего сообщений: {gpt_stats['messages_count']}
✅ Завершений: {gpt_stats['completions_count']}
🔄 Активных диалогов: {gpt_stats['active_conversations']}

<b>📈 Показатели:</b>
🎯 Завершений на тестера: {(self.test_stats['completed_tests'] / max(self.test_stats['total_testers'], 1)):.1f}
💬 Сообщений на завершение: {(self.test_stats['total_test_messages'] / max(self.test_stats['completed_tests'], 1)):.1f}
🔄 Сбросов на тестера: {(self.test_stats['reset_count'] / max(self.test_stats['total_testers'], 1)):.1f}

<i>Обновлено: {datetime.now().strftime('%H:%M:%S')}</i>
        """
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="show_stats")],
            [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")]
        ])
        
        if edit:
            await message.edit_text(stats_text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await message.answer(stats_text, reply_markup=keyboard, parse_mode="HTML")
    
    async def _show_user_info(self, message: Message, edit: bool = False):
        """Показать информацию о диалоге пользователя"""
        user_id = str(message.from_user.id)
        
        try:
            client = await self.rental_bot.get_client_info(user_id)
            
            if client.is_complete and client.final_data:
                # Завершенный диалог
                info_text = f"""
📋 <b>ВАШ ДИАЛОГ (ЗАВЕРШЕН)</b>

✅ <b>Тест успешно пройден!</b>

<b>📊 Статистика диалога:</b>
💬 Сообщений: {client.message_count}
⏰ Создан: {client.created_at.strftime('%d.%m.%Y %H:%M')}
🎯 Статус: Завершен

<b>📋 Извлеченные данные:</b>
{self._format_extracted_data(client.final_data)}

<i>🤖 Данные извлечены GPT автоматически</i>
                """
            elif client.message_count > 0:
                # Диалог в процессе
                dialog_preview = client.raw_data[:300] + "..." if len(client.raw_data) > 300 else client.raw_data
                
                info_text = f"""
📋 <b>ВАШ ДИАЛОГ (В ПРОЦЕССЕ)</b>

⏳ <b>Тестирование продолжается</b>

<b>📊 Статистика:</b>
💬 Сообщений: {client.message_count}
⏰ Начат: {client.created_at.strftime('%d.%m.%Y %H:%M')}
🎯 Статус: В процессе

<b>📝 Последние сообщения:</b>
<code>{dialog_preview}</code>

<i>💡 Продолжайте общение для завершения теста</i>
                """
            else:
                # Новый пользователь
                info_text = """
📋 <b>ВАШ ДИАЛОГ</b>

🆕 <b>Диалог еще не начат</b>

Нажмите "Начать тестирование" чтобы протестировать GPT-ONLY систему.

<i>💡 Общайтесь естественно, как реальный клиент</i>
                """
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🧪 Тестировать", callback_data="start_test")],
                [InlineKeyboardButton(text="🔄 Сбросить", callback_data="reset_dialog")],
                [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")]
            ])
            
            if edit:
                await message.edit_text(info_text, reply_markup=keyboard, parse_mode="HTML")
            else:
                await message.answer(info_text, reply_markup=keyboard, parse_mode="HTML")
                
        except Exception as e:
            error_text = f"❌ Ошибка получения информации: {e}"
            await message.answer(error_text)
    
    def _format_extracted_data(self, data: Dict[str, Any]) -> str:
        """Форматирование извлеченных данных"""
        if not data:
            return "❌ Данные не извлечены"
        
        formatted = []
        
        # Имя
        name = data.get('name', '❌ не указано')
        formatted.append(f"👤 <b>Имя:</b> {name}")
        
        # Телефон
        phone = data.get('phone', '❌ не указан')
        formatted.append(f"📱 <b>Телефон:</b> <code>{phone}</code>")
        
        # Состав семьи
        residents_info = data.get('residents_info', '❌ не указано')
        residents_count = data.get('residents_count', '❌')
        formatted.append(f"🏠 <b>Жильцы:</b> {residents_info}")
        formatted.append(f"👥 <b>Количество:</b> {residents_count}")
        
        # Дети
        children_status = self._format_boolean_field(data.get('has_children'), 'дети')
        formatted.append(f"👶 <b>Дети:</b> {children_status}")
        
        children_details = data.get('children_details')
        if children_details:
            formatted.append(f"   └ <i>{children_details}</i>")
        
        # Животные
        pets_status = self._format_boolean_field(data.get('has_pets'), 'животные')
        formatted.append(f"🐕 <b>Животные:</b> {pets_status}")
        
        pets_details = data.get('pets_details')
        if pets_details:
            formatted.append(f"   └ <i>{pets_details}</i>")
        
        # Срок аренды
        rental_period = data.get('rental_period', '❌ не указан')
        formatted.append(f"📅 <b>Срок:</b> {rental_period}")
        
        # Дата заезда
        move_in = data.get('move_in_deadline', '❌ не указана')
        formatted.append(f"🗓️ <b>Заезд:</b> {move_in}")
        
        return '\n'.join(formatted)
    
    def _format_boolean_field(self, value, field_name: str) -> str:
        """Форматирование булевых полей"""
        if value is True:
            return f"✅ есть"
        elif value is False:
            return f"❌ нет"
        else:
            return f"❓ не указано"
    
    def _format_final_data(self, data: Dict[str, Any]) -> str:
        """Форматирование финальных данных для debug"""
        if not data:
            return "Нет данных"
        
        formatted = []
        for key, value in data.items():
            formatted.append(f"• {key}: {value}")
        
        return '\n'.join(formatted)
    
    # ЗАПУСК И ОСТАНОВКА
    
    async def start(self):
        """Запуск тестового бота"""
        try:
            # Инициализируем GPT ядро
            await self.rental_bot._ensure_initialized()
            
            # Получаем информацию о боте
            bot_info = await self.bot.get_me()
            
            print("🚀 Telegram Test Bot запущен!")
            print(f"📱 Bot: @{bot_info.username}")
            print(f"🧠 GPT модель: {self.rental_bot.config.openai_model}")
            print(f"🌡️ Температура: {self.rental_bot.config.openai_temperature}")
            print("="*50)
            print("💡 Пригласите пользователей для тестирования!")
            print("📊 Статистика будет доступна в реальном времени")
            print("="*50)
            
            self.logger.info(f"Test bot started: @{bot_info.username}")
            
            # Запускаем polling
            await self.dp.start_polling(self.bot, skip_updates=True)
            
        except Exception as e:
            self.logger.error(f"Test bot startup error: {e}")
            raise
        finally:
            await self.bot.session.close()
    
    async def stop(self):
        """Остановка бота"""
        try:
            await self.bot.session.close()
            self.logger.info("Test bot stopped")
        except Exception as e:
            self.logger.error(f"Error stopping test bot: {e}")
    
    def get_test_stats(self) -> Dict[str, Any]:
        """Получить статистику тестирования"""
        return {
            **self.test_stats,
            'active_testers': len(self.active_testers),
            'gpt_stats': self.rental_bot.get_stats(),
            'uptime_seconds': (datetime.now() - self.test_stats['start_time']).total_seconds()
        }


class TelegramTestBotFactory:
    """Фабрика для создания тестового бота"""
    
    @staticmethod
    def create_test_bot(telegram_token: str, openai_key: str) -> TelegramTestBot:
        """Создает тестовый бот"""
        return TelegramTestBot(telegram_token, openai_key)
    
    @staticmethod
    def create_demo_bot(telegram_token: str, openai_key: str) -> TelegramTestBot:
        """Создает демонстрационный бот для презентаций"""
        bot = TelegramTestBot(telegram_token, openai_key)
        
        # Настройки для демо
        bot.rental_bot.config.openai_temperature = 0.9  # Более креативные ответы
        bot.rental_bot.config.openai_max_tokens = 400   # Более длинные ответы
        
        return bot


# Консольный интерфейс для управления тестовым ботом
class TestBotCLI:
    """Консольный интерфейс для тестового бота"""
    
    def __init__(self, bot: TelegramTestBot):
        self.bot = bot
    
    async def run_with_console(self):
        """Запуск с консольным управлением"""
        print("\n🎛️ Test Bot Management Console")
        print("Commands: stats, testers, health, quit")
        
        # Запускаем бота в фоне
        bot_task = asyncio.create_task(self.bot.start())
        
        # Ждем инициализации
        await asyncio.sleep(3)
        
        try:
            while True:
                try:
                    command = input("\n> ").strip().lower()
                    
                    if command in ['quit', 'exit']:
                        break
                    elif command == 'stats':
                        await self._show_stats()
                    elif command == 'testers':
                        await self._show_testers()
                    elif command == 'health':
                        await self._show_health()
                    elif command == 'help':
                        self._show_help()
                    else:
                        print("❌ Unknown command. Type 'help' for available commands.")
                        
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    print(f"❌ Error: {e}")
        
        finally:
            print("\n⏹️ Stopping test bot...")
            await self.bot.stop()
            bot_task.cancel()
    
    async def _show_stats(self):
        """Показать статистику"""
        stats = self.bot.get_test_stats()
        
        print(f"\n📊 Test Bot Statistics:")
        print(f"   👥 Total testers: {stats['total_testers']}")
        print(f"   💬 Test messages: {stats['total_test_messages']}")
        print(f"   ✅ Completed tests: {stats['completed_tests']}")
        print(f"   🔄 Resets: {stats['reset_count']}")
        print(f"   ⏰ Uptime: {stats['uptime_seconds']//3600:.0f}h {(stats['uptime_seconds']%3600)//60:.0f}m")
        
        gpt_stats = stats['gpt_stats']
        print(f"\n🧠 GPT Core:")
        print(f"   👥 Clients: {gpt_stats['users_count']}")
        print(f"   💬 Messages: {gpt_stats['messages_count']}")
        print(f"   ✅ Completions: {gpt_stats['completions_count']}")
    
    async def _show_testers(self):
        """Показать активных тестеров"""
        if not self.bot.active_testers:
            print("\n👥 No active testers")
            return
        
        print(f"\n👥 Active Testers ({len(self.bot.active_testers)}):")
        for user_id, info in self.bot.active_testers.items():
            last_activity = info['last_activity']
            time_since = datetime.now() - last_activity
            
            print(f"   • {info['name']} (ID: {user_id})")
            print(f"     📤 Messages: {info['messages_sent']}")
            print(f"     🔄 Resets: {info['resets_count']}")
            print(f"     ⏰ Last activity: {time_since.seconds//60}m ago")
    
    async def _show_health(self):
        """Показать здоровье системы"""
        try:
            health = await self.bot.rental_bot.health_check()
            
            print(f"\n⚙️ System Health:")
            print(f"   Status: {'✅ Healthy' if health['status'] == 'healthy' else '❌ Unhealthy'}")
            print(f"   Uptime: {health.get('uptime_hours', 0):.1f}h")
            print(f"   Model: {health.get('config', {}).get('model', 'unknown')}")
            print(f"   Temperature: {health.get('config', {}).get('temperature', 0)}")
            
        except Exception as e:
            print(f"❌ Health check failed: {e}")
    
    def _show_help(self):
        """Показать справку"""
        print("\n📖 Available commands:")
        print("   stats    - show test statistics")
        print("   testers  - show active testers")
        print("   health   - system health check")
        print("   quit     - stop the bot")


# Главная функция
async def main():
    """Главная функция запуска тестового бота"""
    
    print("🧪 GPT-ONLY RENTALBOT - TELEGRAM TEST ENVIRONMENT")
    print("="*60)
    print("🎯 Тестирование диалоговой системы в реальном времени")
    print("🤖 Полное воспроизведение продакшн логики через Telegram")
    print("="*60)
    
    try:
        # Получаем переменные окружения
        env_vars = get_required_env_vars()
        
        # Создаем тестовый бот
        test_bot = TelegramTestBotFactory.create_test_bot(
            env_vars['telegram_token'],
            env_vars['openai_key']
        )
        
        # Запускаем бота
        await test_bot.start()
        
    except KeyboardInterrupt:
        print("\n👋 Test bot stopped by user")
    except Exception as e:
        print(f"\n💥 Critical error: {e}")
        sys.exit(1)


# Альтернативный запуск с консольным управлением
async def main_with_console():
    """Запуск с консольным интерфейсом"""
    
    try:
        env_vars = get_required_env_vars()
        
        test_bot = TelegramTestBotFactory.create_test_bot(
            env_vars['telegram_token'],
            env_vars['openai_key']
        )
        
        cli = TestBotCLI(test_bot)
        await cli.run_with_console()
        
    except Exception as e:
        print(f"💥 Error: {e}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Telegram Test Bot for GPT-ONLY RentalBot')
    parser.add_argument('--console', '-c', action='store_true',
                       help='Run with console management interface')
    parser.add_argument('--demo', action='store_true',
                       help='Run in demo mode with enhanced responses')
    
    args = parser.parse_args()
    
    try:
        if args.console:
            # Запуск с консолью
            asyncio.run(main_with_console())
        elif args.demo:
            # Демо режим
            async def demo_mode():
                env_vars = get_required_env_vars()
                demo_bot = TelegramTestBotFactory.create_demo_bot(
                    env_vars['telegram_token'],
                    env_vars['openai_key']
                )
                await demo_bot.start()
            
            asyncio.run(demo_mode())
        else:
            # Обычный запуск
            asyncio.run(main())
            
    except KeyboardInterrupt:
        print("\n👋 Telegram Test Bot stopped")
    except Exception as e:
        print(f"\n💥 Critical error: {e}")
        sys.exit(1)
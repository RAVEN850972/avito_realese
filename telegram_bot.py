#!/usr/bin/env python3
"""
Telegram бот для менеджеров - получение уведомлений о заявках с Avito
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

try:
    from aiogram import Bot, Dispatcher, types, F
    from aiogram.filters import Command, CommandStart
    from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
except ImportError:
    print("❌ Не установлена библиотека aiogram")
    print("💡 Установите: pip install aiogram>=3.0.0")
    exit(1)

from core import RentalBotCore


class TelegramManagerBot:
    """
    Telegram бот для менеджеров - уведомления о заявках
    """
    
    def __init__(self, telegram_token: str, rental_bot: RentalBotCore):
        self.telegram_token = telegram_token
        self.rental_bot = rental_bot
        
        # Telegram бот
        self.bot = Bot(token=telegram_token)
        self.dp = Dispatcher()
        
        # Менеджеры
        self.authorized_managers: set = set()
        self.manager_stats: Dict[int, Dict] = {}
        
        # Статистика
        self.stats = {
            'notifications_sent': 0,
            'managers_active': 0,
            'start_time': datetime.now()
        }
        
        # Регистрируем обработчики
        self._register_handlers()
        
        self.logger = logging.getLogger(__name__)
        
        print("👥 Telegram Manager Bot initialized")
    
    def _register_handlers(self):
        """Регистрация обработчиков"""
        
        # Команды для менеджеров
        self.dp.message(CommandStart())(self.cmd_start)
        self.dp.message(Command("stats"))(self.cmd_stats)
        self.dp.message(Command("leads"))(self.cmd_leads)
        self.dp.message(Command("system"))(self.cmd_system)
        self.dp.message(Command("help"))(self.cmd_help)
        
        # Inline кнопки
        self.dp.callback_query(F.data == "get_stats")(self.btn_get_stats)
        self.dp.callback_query(F.data == "get_leads")(self.btn_get_leads)
        self.dp.callback_query(F.data == "system_status")(self.btn_system_status)
        self.dp.callback_query(F.data.startswith("lead_details_"))(self.btn_lead_details)
    
    # КОМАНДЫ ДЛЯ МЕНЕДЖЕРОВ
    
    async def cmd_start(self, message: Message):
        """Команда /start для менеджеров"""
        manager_id = message.from_user.id
        manager_name = message.from_user.first_name or "Менеджер"
        
        # Добавляем в авторизованные
        self.authorized_managers.add(manager_id)
        self.manager_stats[manager_id] = {
            'name': manager_name,
            'joined': datetime.now(),
            'notifications_received': 0
        }
        
        welcome_text = f"""
👋 <b>Добро пожаловать, {manager_name}!</b>

🏠 <b>GPT-ONLY RentalBot - Панель менеджера</b>

Вы будете получать уведомления о всех завершенных заявках с Avito.

<b>🎯 Как это работает:</b>
1. Клиенты пишут в чаты Avito
2. GPT бот собирает данные
3. Готовые заявки приходят сюда

<b>📊 Доступные команды:</b>
/stats - статистика заявок
/leads - последние заявки  
/system - состояние системы
/help - справка

<i>🤖 Система полностью автоматизирована через GPT</i>
        """
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data="get_stats"),
                InlineKeyboardButton(text="📋 Заявки", callback_data="get_leads")
            ],
            [
                InlineKeyboardButton(text="⚙️ Система", callback_data="system_status")
            ]
        ])
        
        await message.answer(welcome_text, reply_markup=keyboard, parse_mode="HTML")
        
        self.logger.info(f"Manager {manager_name} ({manager_id}) authorized")
    
    async def cmd_stats(self, message: Message):
        """Статистика системы"""
        if not self._is_authorized(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            bot_stats = self.rental_bot.get_stats()
            system_uptime = datetime.now() - self.stats['start_time']
            
            stats_text = f"""
📊 <b>СТАТИСТИКА СИСТЕМЫ</b>

<b>🏠 Общие показатели:</b>
👥 Всего клиентов: {bot_stats['users_count']}
✅ Завершенных заявок: {bot_stats['completions_count']}
💬 Всего сообщений: {bot_stats['messages_count']}
⏰ Время работы: {system_uptime.days}д {system_uptime.seconds//3600}ч

<b>👥 Менеджеры:</b>
🔢 Активных: {len(self.authorized_managers)}
📩 Уведомлений отправлено: {self.stats['notifications_sent']}

<b>📈 Эффективность:</b>
🎯 Конверсия: {(bot_stats['completions_count'] / max(bot_stats['users_count'], 1) * 100):.1f}%
💬 Сообщений на заявку: {(bot_stats['messages_count'] / max(bot_stats['completions_count'], 1)):.1f}

<i>Обновлено: {datetime.now().strftime('%H:%M:%S')}</i>
            """
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Обновить", callback_data="get_stats")]
            ])
            
            await message.answer(stats_text, reply_markup=keyboard, parse_mode="HTML")
            
        except Exception as e:
            await message.answer(f"❌ Ошибка получения статистики: {e}")
    
    async def cmd_leads(self, message: Message):
        """Последние заявки"""
        if not self._is_authorized(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            # Получаем всех клиентов с завершенными диалогами
            all_clients = await self.rental_bot.get_all_clients()
            completed_clients = [c for c in all_clients if c.is_complete and c.final_data]
            
            # Сортируем по времени создания (новые сначала)
            completed_clients.sort(key=lambda x: x.created_at, reverse=True)
            
            if not completed_clients:
                await message.answer("📭 Пока нет завершенных заявок")
                return
            
            # Показываем последние 10
            recent_clients = completed_clients[:10]
            
            leads_text = f"""
📋 <b>ПОСЛЕДНИЕ ЗАЯВКИ ({len(recent_clients)} из {len(completed_clients)})</b>

"""
            
            buttons = []
            for i, client in enumerate(recent_clients, 1):
                name = client.final_data.get('name', 'Не указано')
                phone = client.final_data.get('phone', 'Не указан')
                created = client.created_at.strftime('%d.%m %H:%M')
                
                leads_text += f"""
<b>{i}.</b> {name}
📱 {phone}
⏰ {created}
─────────────────
"""
                
                # Кнопка для деталей
                buttons.append([InlineKeyboardButton(
                    text=f"📄 Детали #{i}",
                    callback_data=f"lead_details_{client.user_id}"
                )])
            
            # Ограничиваем количество кнопок
            if len(buttons) > 5:
                buttons = buttons[:5]
                leads_text += f"\n<i>Показано 5 из {len(recent_clients)} заявок</i>"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            
            await message.answer(leads_text, reply_markup=keyboard, parse_mode="HTML")
            
        except Exception as e:
            await message.answer(f"❌ Ошибка получения заявок: {e}")
    
    async def cmd_system(self, message: Message):
        """Состояние системы"""
        if not self._is_authorized(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        try:
            health = await self.rental_bot.health_check()
            
            status_icon = "✅" if health['status'] == 'healthy' else "❌"
            
            system_text = f"""
⚙️ <b>СОСТОЯНИЕ СИСТЕМЫ</b>

{status_icon} <b>Статус:</b> {health['status']}
⏰ <b>Время работы:</b> {health['uptime_hours']:.1f} часов

<b>🧠 GPT Ядро:</b>
📊 Клиентов: {health['stats']['total_clients']}
✅ Завершено: {health['stats']['completed_clients']}
💬 Сообщений: {health['stats']['total_messages']}

<b>🔧 Конфигурация:</b>
🤖 Модель: {health['config']['model']}
🌡️ Температура: {health['config']['temperature']}
🎯 Токенов: {health['config']['max_tokens']}

<b>📊 База данных:</b>
💾 Путь: {health['config']['database_path']}

<i>Проверено: {health['timestamp'][:19]}</i>
            """
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Обновить", callback_data="system_status")]
            ])
            
            await message.answer(system_text, reply_markup=keyboard, parse_mode="HTML")
            
        except Exception as e:
            await message.answer(f"❌ Ошибка проверки системы: {e}")
    
    async def cmd_help(self, message: Message):
        """Справка для менеджеров"""
        if not self._is_authorized(message.from_user.id):
            await message.answer("❌ Доступ запрещен")
            return
        
        help_text = """
📖 <b>СПРАВКА ДЛЯ МЕНЕДЖЕРОВ</b>

<b>🎯 Основные команды:</b>
/start - главное меню
/stats - статистика системы
/leads - последние заявки
/system - техническое состояние
/help - эта справка

<b>🔄 Как работает система:</b>
1. <b>Клиенты</b> пишут в чаты Avito по объявлению
2. <b>GPT бот</b> автоматически отвечает и собирает данные
3. <b>Готовые заявки</b> приходят вам уведомлениями
4. <b>Вы связываетесь</b> с клиентом по указанному телефону

<b>📩 Уведомления содержат:</b>
• Имя и телефон клиента
• Состав семьи и количество жильцов
• Наличие детей и животных
• Желаемый срок аренды
• Дату заезда
• ID чата Avito для справки

<b>🧠 Особенности GPT-ONLY режима:</b>
✅ Естественное живое общение
✅ Понимание контекста и нюансов
✅ Автоматическая обработка сложных случаев
✅ Извлечение данных без программных шаблонов

<b>⚡ В случае проблем:</b>
• Проверьте /system для диагностики
• Убедитесь что система показывает статус "healthy"
• Обратитесь к администратору если ошибки

<i>🏠 GPT-ONLY RentalBot System v4.0</i>
        """
        
        await message.answer(help_text, parse_mode="HTML")
    
    # ОБРАБОТЧИКИ КНОПОК
    
    async def btn_get_stats(self, callback: CallbackQuery):
        """Кнопка статистики"""
        await callback.message.delete()
        await self.cmd_stats(callback.message)
        await callback.answer()
    
    async def btn_get_leads(self, callback: CallbackQuery):
        """Кнопка заявок"""
        await callback.message.delete()
        await self.cmd_leads(callback.message)
        await callback.answer()
    
    async def btn_system_status(self, callback: CallbackQuery):
        """Кнопка состояния системы"""
        await callback.message.delete()
        await self.cmd_system(callback.message)
        await callback.answer()
    
    async def btn_lead_details(self, callback: CallbackQuery):
        """Детали конкретной заявки"""
        if not self._is_authorized(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен")
            return
        
        try:
            # Извлекаем user_id из callback_data
            user_id = callback.data.replace("lead_details_", "")
            
            # Получаем клиента
            client = await self.rental_bot.get_client_info(user_id)
            
            if not client or not client.final_data:
                await callback.answer("❌ Заявка не найдена")
                return
            
            # Форматируем детальную информацию
            details_text = f"""
📋 <b>ДЕТАЛИ ЗАЯВКИ</b>

👤 <b>Имя:</b> {client.final_data.get('name', 'не указано')}
📱 <b>Телефон:</b> <code>{client.final_data.get('phone', 'не указан')}</code>

🏠 <b>Состав семьи:</b>
{client.final_data.get('residents_info', 'не указано')}

👥 <b>Количество жильцов:</b> {client.final_data.get('residents_count', 'не указано')}

👶 <b>Дети:</b> {'✅ есть' if client.final_data.get('has_children') else '❌ нет' if client.final_data.get('has_children') is not None else '❓ не указано'}
{f"   Детали: {client.final_data.get('children_details', '')}" if client.final_data.get('children_details') else ""}

🐕 <b>Животные:</b> {'✅ есть' if client.final_data.get('has_pets') else '❌ нет' if client.final_data.get('has_pets') is not None else '❓ не указано'}
{f"   Детали: {client.final_data.get('pets_details', '')}" if client.final_data.get('pets_details') else ""}

📅 <b>Срок аренды:</b> {client.final_data.get('rental_period', 'не указан')}
🗓️ <b>Дата заезда:</b> {client.final_data.get('move_in_deadline', 'не указана')}

📊 <b>Статистика диалога:</b>
💬 Сообщений: {client.message_count}
⏰ Создан: {client.created_at.strftime('%d.%m.%Y %H:%M')}
🆔 ID: <code>{client.user_id}</code>

<i>🤖 Обработано GPT-ONLY ботом</i>
            """
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📞 Скопировать телефон", callback_data=f"copy_phone_{client.user_id}")],
                [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="get_leads")]
            ])
            
            await callback.message.edit_text(details_text, reply_markup=keyboard, parse_mode="HTML")
            
        except Exception as e:
            await callback.answer(f"❌ Ошибка: {e}")
    
    # УВЕДОМЛЕНИЯ МЕНЕДЖЕРАМ
    
    async def send_completion_notification(self, notification_data: Dict[str, Any]):
        """Отправка уведомления о завершенной заявке всем менеджерам"""
        
        if not self.authorized_managers:
            self.logger.warning("No authorized managers to send notification")
            return
        
        message = self._format_avito_notification(notification_data)
        
        sent_count = 0
        for manager_id in self.authorized_managers.copy():
            try:
                await self.bot.send_message(manager_id, message, parse_mode="HTML")
                
                # Обновляем статистику менеджера
                if manager_id in self.manager_stats:
                    self.manager_stats[manager_id]['notifications_received'] += 1
                
                sent_count += 1
                
            except Exception as e:
                self.logger.error(f"Failed to send notification to manager {manager_id}: {e}")
                # Удаляем неактивного менеджера
                self.authorized_managers.discard(manager_id)
        
        self.stats['notifications_sent'] += sent_count
        self.logger.info(f"Notification sent to {sent_count} managers")
    
    def _format_avito_notification(self, data: Dict[str, Any]) -> str:
        """Форматирование уведомления с Avito"""
        
        extracted = data.get('extracted_data', {})
        
        # Определяем эмодзи для детей и животных
        children_emoji = "👶✅" if extracted.get('has_children') else "👶❌" if extracted.get('has_children') is not None else "👶❓"
        pets_emoji = "🐕✅" if extracted.get('has_pets') else "🐕❌" if extracted.get('has_pets') is not None else "🐕❓"
        
        message = f"""
🎉 <b>НОВАЯ ЗАЯВКА С AVITO!</b>

👤 <b>{extracted.get('name', '❌ не указано')}</b>
📱 <b>Телефон:</b> <code>{extracted.get('phone', '❌ не указан')}</code>

🏠 <b>Жильцы:</b> {extracted.get('residents_info', '❌ не указано')}
👥 <b>Количество:</b> {extracted.get('residents_count', '❌')} чел.

{children_emoji} <b>Дети:</b> {'есть' if extracted.get('has_children') else 'нет' if extracted.get('has_children') is not None else 'не указано'}
{pets_emoji} <b>Животные:</b> {'есть' if extracted.get('has_pets') else 'нет' if extracted.get('has_pets') is not None else 'не указано'}

📅 <b>Срок:</b> {extracted.get('rental_period', '❌ не указан')}
🗓️ <b>Заезд:</b> {extracted.get('move_in_deadline', '❌ не указана')}

📊 <b>Источник:</b> Avito (чат: <code>{data.get('chat_id', 'не указан')}</code>)
⏰ <b>Время:</b> {data.get('completed_at', 'не указано')[:16]}

<i>🤖 Обработано GPT-ONLY ботом автоматически</i>
        """
        
        return message
    
    # УТИЛИТЫ
    
    def _is_authorized(self, user_id: int) -> bool:
        """Проверка авторизации менеджера"""
        return user_id in self.authorized_managers
    
    def add_manager(self, manager_id: int, manager_name: str = "Manager"):
        """Добавление менеджера"""
        self.authorized_managers.add(manager_id)
        self.manager_stats[manager_id] = {
            'name': manager_name,
            'joined': datetime.now(),
            'notifications_received': 0
        }
        self.logger.info(f"Manager {manager_name} ({manager_id}) added")
    
    def remove_manager(self, manager_id: int):
        """Удаление менеджера"""
        self.authorized_managers.discard(manager_id)
        self.manager_stats.pop(manager_id, None)
        self.logger.info(f"Manager {manager_id} removed")
    
    def get_manager_stats(self) -> Dict[str, Any]:
        """Статистика менеджеров"""
        return {
            'total_managers': len(self.authorized_managers),
            'notifications_sent': self.stats['notifications_sent'],
            'managers': self.manager_stats,
            'uptime_hours': (datetime.now() - self.stats['start_time']).total_seconds() / 3600
        }
    
    # ЗАПУСК (НЕ используется в продакшене - только для отправки уведомлений)
    
    async def start_polling(self):
        """Запуск бота (только для тестирования)"""
        try:
            bot_info = await self.bot.get_me()
            self.logger.info(f"Manager bot started: @{bot_info.username}")
            
            # В продакшене этот метод НЕ вызывается
            # Бот используется только для отправки уведомлений
            await self.dp.start_polling(self.bot)
            
        except Exception as e:
            self.logger.error(f"Manager bot error: {e}")
            raise
        finally:
            await self.bot.session.close()
    
    async def stop(self):
        """Остановка бота"""
        try:
            await self.bot.session.close()
            self.logger.info("Manager bot stopped")
        except Exception as e:
            self.logger.error(f"Error stopping manager bot: {e}")


class TelegramManagerBotFactory:
    """Фабрика для создания менеджерского бота"""
    
    @staticmethod
    def create_manager_notification_bot(telegram_token: str, rental_bot: RentalBotCore) -> TelegramManagerBot:
        """Создает бота для уведомлений менеджеров"""
        return TelegramManagerBot(telegram_token, rental_bot)
    
    @staticmethod
    def create_manager_bot_with_predefined_managers(
        telegram_token: str, 
        rental_bot: RentalBotCore,
        manager_ids: List[int]
    ) -> TelegramManagerBot:
        """Создает бота с предустановленными менеджерами"""
        
        bot = TelegramManagerBot(telegram_token, rental_bot)
        
        # Добавляем менеджеров
        for manager_id in manager_ids:
            bot.add_manager(manager_id)
        
        return bot


# Пример использования
async def example_manager_bot():
    """Пример использования менеджерского бота"""
    
    from core import RentalBotCore
    
    # Создаем компоненты
    rental_bot = RentalBotCore("test-key")
    manager_bot = TelegramManagerBot("telegram-token", rental_bot)
    
    # Добавляем менеджеров
    manager_bot.add_manager(123456789, "Иван Менеджеров")
    manager_bot.add_manager(987654321, "Анна Управляющая")
    
    # Симулируем уведомление
    test_notification = {
        'source': 'avito',
        'chat_id': 'test_chat_123',
        'client_name': 'Тестовый Клиент',
        'extracted_data': {
            'name': 'Иван Тестов',
            'phone': '+79123456789',
            'residents_info': 'семья из 2 человек',
            'residents_count': 2,
            'has_children': False,
            'has_pets': True,
            'rental_period': '1 год',
            'move_in_deadline': 'до 15 декабря'
        },
        'completed_at': datetime.now().isoformat()
    }
    
    await manager_bot.send_completion_notification(test_notification)


if __name__ == "__main__":
    asyncio.run(example_manager_bot())
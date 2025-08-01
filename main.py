#!/usr/bin/env python3
"""
Главный файл GPT-ONLY RentalBot с реальной Avito интеграцией
Система работает следующим образом:
1. Клиенты пишут в чаты Avito
2. GPT бот отвечает через Avito API
3. Завершенные заявки отправляются менеджерам в Telegram
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from typing import Optional, List

# Добавляем путь к проекту
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Загружаем переменные окружения
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("💡 Рекомендуется установить python-dotenv: pip install python-dotenv")

# Импорты модулей проекта
from config import get_required_env_vars, get_config
from core import RentalBotCore, BotBuilder, ClientInfo
from telegram_bot import TelegramBot, TelegramBotFactory
from telegram_bot import TelegramManagerBot, TelegramManagerBotFactory
from avito_integration import (
    AvitoAPIClient, AvitoGPTBot, TelegramAvitoNotifier,
    AvitoIntegrationFactory, AvitoConfig
)


class ProductionRentalBotSystem:
    """
    Продакшн система GPT-ONLY RentalBot с Avito интеграцией
    """
    
    def __init__(self):
        self.logger = self._setup_logging()
        
        # Основные компоненты
        self.rental_bot: Optional[RentalBotCore] = None
        self.telegram_manager_bot: Optional[TelegramManagerBot] = None
        self.avito_bot: Optional[AvitoGPTBot] = None
        self.avito_client: Optional[AvitoAPIClient] = None
        
        # Конфигурация
        self.avito_config = AvitoConfig()
        
        # Состояние системы
        self.is_running = False
        self.start_time = datetime.now()
        
        # Статистика
        self.system_stats = {
            'avito_messages_processed': 0,
            'telegram_notifications_sent': 0,
            'gpt_completions': 0,
            'total_errors': 0,
            'start_time': self.start_time
        }
        
        print("🚀 Production GPT-ONLY RentalBot System with Avito Integration")
    
    def _setup_logging(self) -> logging.Logger:
        """Настройка логирования"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('production_rental_bot.log'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        return logging.getLogger(__name__)
    
    async def initialize(self):
        """Инициализация всех компонентов системы"""
        try:
            self.logger.info("Starting production system initialization...")
            
            # Загружаем переменные окружения
            env_vars = get_required_env_vars()
            
            # Конфигурация Avito
            await self._load_avito_config()
            
            # Инициализируем GPT ядро
            await self._initialize_gpt_core(env_vars['openai_key'])
            
            # Инициализируем Telegram бот (для менеджеров)
            await self._initialize_telegram_for_managers(env_vars['telegram_token'])
            
            # Инициализируем Avito интеграцию
            await self._initialize_avito_integration()
            
            self.logger.info("✅ All components initialized successfully")
            
        except Exception as e:
            self.logger.error(f"❌ System initialization failed: {e}")
            raise
    
    async def _load_avito_config(self):
        """Загрузка конфигурации Avito"""
        
        # Получаем параметры из переменных окружения
        self.avito_config.access_token = os.getenv("AVITO_ACCESS_TOKEN")
        self.avito_config.user_id = int(os.getenv("AVITO_USER_ID", "0"))
        
        # ID чатов менеджеров в Telegram
        manager_ids_str = os.getenv("MANAGER_TELEGRAM_IDS", "")
        if manager_ids_str:
            self.avito_config.manager_chat_ids = [
                int(id.strip()) for id in manager_ids_str.split(",") if id.strip()
            ]
        
        # Настройки мониторинга
        self.avito_config.polling_interval = int(os.getenv("AVITO_POLLING_INTERVAL", "10"))
        self.avito_config.rate_limit_delay = float(os.getenv("AVITO_RATE_LIMIT_DELAY", "1.0"))
        
        # Валидация конфигурации
        if not self.avito_config.access_token:
            raise ValueError("❌ AVITO_ACCESS_TOKEN не установлен")
        
        if not self.avito_config.user_id:
            raise ValueError("❌ AVITO_USER_ID не установлен")
        
        self.logger.info(f"✅ Avito config loaded: user_id={self.avito_config.user_id}")
        self.logger.info(f"   Managers: {len(self.avito_config.manager_chat_ids)} configured")
    
    async def _initialize_gpt_core(self, openai_key: str):
        """Инициализация GPT ядра"""
        self.logger.info("Initializing GPT core...")
        
        # Создаем GPT ядро с обработчиками
        self.rental_bot = (BotBuilder(openai_key)
                          .with_completion_handler(self._handle_gpt_completion)
                          .with_error_handler(self._handle_gpt_error)
                          .with_database("production_rental.db")
                          .enable_logging(True)
                          .enable_stats(True)
                          .build())
        
        # Проверяем здоровье
        health = await self.rental_bot.health_check()
        if health['status'] != 'healthy':
            raise Exception(f"GPT core is not healthy: {health}")
        
        self.logger.info("✅ GPT core initialized")
    
    async def _initialize_telegram_for_managers(self, telegram_token: str):
        """Инициализация Telegram бота для менеджеров"""
        self.logger.info("Initializing Telegram for managers...")
        
        # Создаем специальный Telegram бот для менеджеров
        self.telegram_manager_bot = TelegramManagerBotFactory.create_manager_bot_with_predefined_managers(
            telegram_token,
            self.rental_bot,
            self.avito_config.manager_chat_ids
        )
        
        self.logger.info("✅ Telegram manager bot initialized")
    
    async def _initialize_avito_integration(self):
        """Инициализация Avito интеграции"""
        self.logger.info("Initializing Avito integration...")
        
        # Создаем Avito API клиент
        self.avito_client = AvitoAPIClient(
            self.avito_config.access_token,
            self.avito_config.user_id
        )
        
        # Создаем уведомитель для Telegram
        telegram_notifier = None
        if self.telegram_manager_bot and self.avito_config.manager_chat_ids:
            # Используем менеджерский бот для уведомлений
            telegram_notifier = self.telegram_manager_bot
        
        # Создаем основной Avito бот
        self.avito_bot = AvitoGPTBot(
            self.avito_client,
            self.rental_bot,
            telegram_notifier
        )
        
        # Тестируем подключение к Avito API
        try:
            async with self.avito_client as client:
                test_chats = await client.get_chats(limit=1)
                self.logger.info(f"✅ Avito API connection successful")
        except Exception as e:
            self.logger.warning(f"⚠️ Avito API test failed: {e}")
        
        self.logger.info("✅ Avito integration initialized")
    
    # ОБРАБОТЧИКИ СОБЫТИЙ
    
    async def _handle_gpt_completion(self, client: ClientInfo):
        """Обработчик завершения диалога в GPT"""
        self.system_stats['gpt_completions'] += 1
        
        self.logger.info(f"✅ GPT dialog completed for {client.user_id}")
        
        # Выводим заявку в консоль для мониторинга
        await self._print_completion_summary(client)
    
    async def _handle_gpt_error(self, user_id: str, message: str, error: Exception):
        """Обработчик ошибок GPT"""
        self.system_stats['total_errors'] += 1
        self.logger.error(f"❌ GPT error for {user_id}: {error}")
    
    async def _print_completion_summary(self, client: ClientInfo):
        """Красивый вывод завершенной заявки"""
        print("\n" + "="*80)
        print("🎉 НОВАЯ ЗАЯВКА ЧЕРЕЗ AVITO + GPT!")
        print("="*80)
        
        if client.final_data:
            print(f"👤 Имя: {client.final_data.get('name', 'не указано')}")
            print(f"📱 Телефон: {client.final_data.get('phone', 'не указан')}")
            print(f"🏠 Состав семьи: {client.final_data.get('residents_info', 'не указано')}")
            print(f"👥 Количество жильцов: {client.final_data.get('residents_count', 'не указано')}")
            print(f"👶 Дети: {'есть' if client.final_data.get('has_children') else 'нет'}")
            print(f"🐕 Животные: {'есть' if client.final_data.get('has_pets') else 'нет'}")
            print(f"📅 Срок аренды: {client.final_data.get('rental_period', 'не указан')}")
            print(f"🗓️ Дата заезда: {client.final_data.get('move_in_deadline', 'не указана')}")
        
        print(f"📊 Сообщений в диалоге: {client.message_count}")
        print(f"🌐 Источник: Avito Messenger")
        print(f"⏰ Время создания: {client.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print("🤖 Полностью управлялось GPT через Avito API")
        print("="*80 + "\n")
    
    # ЗАПУСК И ОСТАНОВКА СИСТЕМЫ
    
    async def start(self):
        """Запуск всей продакшн системы"""
        try:
            self.logger.info("🚀 Starting Production GPT-ONLY RentalBot System...")
            
            await self.initialize()
            
            # Запускаем компоненты параллельно
            tasks = []
            
            # НЕ запускаем Telegram polling для клиентов
            # Telegram теперь только для уведомлений менеджеров
            
            # Запуск мониторинга Avito чатов (основной процесс)
            if self.avito_bot and self.avito_client:
                tasks.append(self._run_avito_monitoring())
            
            # Запуск системного мониторинга
            tasks.append(self._system_monitoring_loop())
            
            self.is_running = True
            
            # Выводим статус запуска
            await self._print_startup_status()
            
            # Запускаем все задачи
            await asyncio.gather(*tasks)
            
        except Exception as e:
            self.logger.error(f"💥 Critical startup error: {e}")
            await self.stop()
            raise
    
    async def _run_avito_monitoring(self):
        """Запуск мониторинга Avito с управлением контекстом"""
        try:
            async with self.avito_client:
                await self.avito_bot.start_monitoring()
        except Exception as e:
            self.logger.error(f"Avito monitoring error: {e}")
            raise
    
    async def stop(self):
        """Остановка всей системы"""
        self.logger.info("⏹️ Stopping system...")
        
        self.is_running = False
        
        # Останавливаем компоненты
        if self.telegram_bot:
            await self.telegram_bot.stop()
        
        self.logger.info("✅ System stopped")
    
    async def _system_monitoring_loop(self):
        """Системный мониторинг"""
        while self.is_running:
            try:
                await asyncio.sleep(300)  # Каждые 5 минут
                
                if not self.is_running:
                    break
                
                # Получаем статистику
                await self._log_system_stats()
                
                # Проверяем здоровье компонентов
                await self._health_check_all()
                
                # Каждые 30 минут выводим детальную статистику
                if datetime.now().minute % 30 == 0:
                    await self._print_detailed_stats()
                
            except Exception as e:
                self.logger.error(f"System monitoring error: {e}")
                await asyncio.sleep(60)
    
    async def _log_system_stats(self):
        """Логирование статистики системы"""
        
        stats = {
            'gpt_completions': self.system_stats['gpt_completions'],
            'total_errors': self.system_stats['total_errors']
        }
        
        if self.avito_bot:
            avito_stats = self.avito_bot.get_stats()
            stats.update({
                'avito_messages': avito_stats['messages_processed'],
                'active_dialogs': avito_stats['active_dialogs']
            })
        
        if self.rental_bot:
            bot_stats = self.rental_bot.get_stats()
            stats.update({
                'total_clients': bot_stats['users_count'],
                'total_messages': bot_stats['messages_count']
            })
        
        self.logger.info(f"System stats: {stats}")
    
    async def _health_check_all(self):
        """Проверка здоровья всех компонентов"""
        try:
            # Проверяем GPT ядро
            if self.rental_bot:
                health = await self.rental_bot.health_check()
                if health['status'] != 'healthy':
                    self.logger.warning(f"⚠️ GPT core issue: {health}")
            
            # Проверяем Avito API (простой запрос)
            if self.avito_client:
                async with self.avito_client as client:
                    await client.get_chats(limit=1)
                    
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
    
    async def _print_startup_status(self):
        """Статус запуска системы"""
        print("\n" + "="*80)
        print("🚀 PRODUCTION GPT-ONLY RENTALBOT SYSTEM ACTIVE!")
        print("="*80)
        print("🎯 РЕЖИМ: PRODUCTION с Avito интеграцией")
        print("✅ КОМПОНЕНТЫ:")
        
        if self.rental_bot:
            print("   🧠 GPT Ядро: АКТИВНО")
        
        if self.avito_bot:
            print("   🏠 Avito Мониторинг: АКТИВНО")
        
        if self.telegram_bot:
            print("   📱 Telegram Уведомления: АКТИВНО")
        
        print(f"   👥 Менеджеров подключено: {len(self.avito_config.manager_chat_ids)}")
        
        print("\n🔄 ПРОЦЕСС РАБОТЫ:")
        print("   1. Клиенты пишут в чаты Avito")
        print("   2. GPT отвечает через Avito API")
        print("   3. Завершенные заявки → Telegram менеджерам")
        
        print(f"\n⏰ Запущено: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🔍 Интервал проверки Avito: {self.avito_config.polling_interval}с")
        print("="*80 + "\n")
    
    async def _print_detailed_stats(self):
        """Детальная статистика"""
        uptime = datetime.now() - self.start_time
        
        print("\n" + "="*60)
        print("📊 ДЕТАЛЬНАЯ СТАТИСТИКА СИСТЕМЫ")
        print("="*60)
        print(f"⏰ Время работы: {uptime}")
        print(f"✅ GPT завершений: {self.system_stats['gpt_completions']}")
        print(f"❌ Ошибок: {self.system_stats['total_errors']}")
        
        if self.avito_bot:
            avito_stats = self.avito_bot.get_stats()
            print(f"💬 Сообщений Avito: {avito_stats['messages_processed']}")
            print(f"🔄 Активных диалогов: {avito_stats['active_dialogs']}")
            print(f"📈 Сообщений/час: {avito_stats['processed_messages_per_hour']:.1f}")
        
        if self.rental_bot:
            bot_stats = self.rental_bot.get_stats()
            print(f"👥 Всего клиентов: {bot_stats['users_count']}")
            print(f"💬 Всего сообщений: {bot_stats['messages_count']}")
        
        print("="*60 + "\n")
    
    # УТИЛИТЫ ДЛЯ УПРАВЛЕНИЯ
    
    async def get_system_status(self) -> dict:
        """Полный статус системы"""
        status = {
            'is_running': self.is_running,
            'start_time': self.start_time.isoformat(),
            'uptime_seconds': (datetime.now() - self.start_time).total_seconds(),
            'components': {},
            'stats': self.system_stats.copy()
        }
        
        # Статус компонентов
        if self.rental_bot:
            status['components']['gpt_core'] = await self.rental_bot.health_check()
        
        if self.avito_bot:
            status['components']['avito_bot'] = self.avito_bot.get_stats()
        
        if self.telegram_bot:
            status['components']['telegram_bot'] = {'status': 'active'}
        
        return status
    
    async def send_test_notification(self, test_data: dict = None):
        """Отправка тестового уведомления менеджерам"""
        if not self.avito_bot or not self.avito_bot.telegram_notifier:
            self.logger.warning("Telegram notifier not available")
            return False
        
        test_notification = test_data or {
            'source': 'avito',
            'chat_id': 'test_chat_123',
            'client_name': 'Тестовый Клиент',
            'client_user_id': 12345,
            'item_id': 67890,
            'extracted_data': {
                'name': 'Иван Тестов',
                'phone': '+79123456789',
                'residents_info': 'семья из 2 человек',
                'residents_count': 2,
                'has_children': False,
                'has_pets': True,
                'pets_details': 'кот',
                'rental_period': '1 год',
                'move_in_deadline': 'до 15 декабря'
            },
            'completed_at': datetime.now().isoformat()
        }
        
        try:
            await self.avito_bot.telegram_notifier.send_completion_notification(test_notification)
            self.logger.info("✅ Test notification sent")
            return True
        except Exception as e:
            self.logger.error(f"❌ Test notification failed: {e}")
            return False


# Консольный интерфейс для управления продакшн системой
class ProductionCLI:
    """Консольный интерфейс для продакшн системы"""
    
    def __init__(self, system: ProductionRentalBotSystem):
        self.system = system
    
    async def run_interactive_mode(self):
        """Интерактивный режим управления"""
        print("\n🎛️ Production System Management Console")
        print("Commands: status, stats, health, test-notification, avito-stats, quit")
        
        while self.system.is_running:
            try:
                command = input("\n> ").strip().lower()
                
                if command in ['quit', 'exit']:
                    break
                elif command == 'status':
                    await self._show_status()
                elif command == 'stats':
                    await self._show_stats()
                elif command == 'health':
                    await self._health_check()
                elif command == 'test-notification':
                    await self._test_notification()
                elif command == 'avito-stats':
                    await self._show_avito_stats()
                elif command == 'help':
                    self._show_help()
                else:
                    print("❌ Unknown command. Type 'help' for available commands.")
                    
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"❌ Error: {e}")
    
    async def _show_status(self):
        """Показать статус системы"""
        status = await self.system.get_system_status()
        print(f"\n📊 System Status:")
        print(f"   Running: {'✅' if status['is_running'] else '❌'}")
        print(f"   Uptime: {status['uptime_seconds']//3600:.0f}h {(status['uptime_seconds']%3600)//60:.0f}m")
        print(f"   Components: {len(status['components'])}")
        print(f"   GPT Completions: {status['stats']['gpt_completions']}")
        print(f"   Total Errors: {status['stats']['total_errors']}")
    
    async def _show_stats(self):
        """Показать статистику"""
        await self.system._print_detailed_stats()
    
    async def _health_check(self):
        """Проверка здоровья"""
        await self.system._health_check_all()
        print("✅ Health check completed")
    
    async def _test_notification(self):
        """Тестовое уведомление"""
        success = await self.system.send_test_notification()
        print("✅ Test notification sent" if success else "❌ Test notification failed")
    
    async def _show_avito_stats(self):
        """Статистика Avito"""
        if self.system.avito_bot:
            stats = self.system.avito_bot.get_stats()
            print(f"\n🏠 Avito Statistics:")
            print(f"   Messages processed: {stats['messages_processed']}")
            print(f"   Active dialogs: {stats['active_dialogs']}")
            print(f"   Messages per hour: {stats['processed_messages_per_hour']:.1f}")
            print(f"   Uptime: {stats['uptime_hours']:.1f}h")
        else:
            print("❌ Avito bot not available")
    
    def _show_help(self):
        """Показать справку"""
        print("\n📖 Available commands:")
        print("   status           - system status")
        print("   stats            - detailed statistics")
        print("   health           - health check")
        print("   test-notification - send test notification")
        print("   avito-stats      - Avito specific stats")
        print("   quit             - exit")


# Главная функция
async def main():
    """Главная функция запуска продакшн системы"""
    
    print("🏭 GPT-ONLY RENTALBOT PRODUCTION SYSTEM")
    print("="*60)
    print("🔄 АРХИТЕКТУРА:")
    print("   Клиенты → Avito чаты → GPT бот → Менеджеры Telegram")
    print("="*60)
    
    # Создаем продакшн систему
    system = ProductionRentalBotSystem()
    
    try:
        # Запускаем систему
        await system.start()
        
    except KeyboardInterrupt:
        print("\n👋 Received stop signal")
    except Exception as e:
        print(f"\n💥 Critical error: {e}")
    finally:
        await system.stop()


# Альтернативный запуск с интерактивным управлением
async def main_interactive():
    """Запуск с интерактивным управлением"""
    
    system = ProductionRentalBotSystem()
    cli = ProductionCLI(system)
    
    try:
        # Запускаем систему в фоне
        system_task = asyncio.create_task(system.start())
        
        # Ждем инициализации
        await asyncio.sleep(5)
        
        # Запускаем интерактивный режим
        await cli.run_interactive_mode()
        
        # Останавливаем систему
        await system.stop()
        system_task.cancel()
        
    except Exception as e:
        print(f"💥 Error: {e}")
        await system.stop()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Production GPT-ONLY RentalBot System')
    parser.add_argument('--interactive', '-i', action='store_true',
                       help='Run in interactive management mode')
    parser.add_argument('--test-notification', action='store_true',
                       help='Send test notification and exit')
    
    args = parser.parse_args()
    
    try:
        if args.test_notification:
            # Быстрый тест уведомлений
            async def test_only():
                system = ProductionRentalBotSystem()
                await system.initialize()
                success = await system.send_test_notification()
                print("✅ Test completed" if success else "❌ Test failed")
                await system.stop()
            
            asyncio.run(test_only())
            
        elif args.interactive:
            # Интерактивный режим
            asyncio.run(main_interactive())
        else:
            # Обычный запуск
            asyncio.run(main())
            
    except KeyboardInterrupt:
        print("\n👋 Production GPT-ONLY RentalBot System stopped")
    except Exception as e:
        print(f"\n💥 Critical error: {e}")
        sys.exit(1)
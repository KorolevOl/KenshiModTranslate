# -*- coding: utf-8 -*-
# Patch AttachmentOptimization.dll: EN UI-strings -> RU (in-place, shorter-or-equal only)
import os, sys
P = r'E:\steamlibrary\steamapps\workshop\content\233860\3731036037\dll\AttachmentOptimization\AttachmentOptimization.dll'
B = bytearray(open(P, 'rb').read())

PAIRS = [
    ("Optimizes weapon rendering", "Оружие"),
    ("Optimizes backpack rendering", "Рюкзак"),
    ("Optimizes hair rendering", "Волосы"),
    ("Optimizes beard rendering", "Борода"),
    ("Optimizes belt-slot attachment rendering", "Пояс"),
    ("Optimizes eye-slot attachment rendering", "Глаза"),
    ("Optimizes glove-slot attachment rendering", "Перчатки"),
    ("Optimizes neck-slot attachment rendering", "Шея"),
    ("Optimizes shirt rendering", "Рубашка"),
    ("Optimizes helmet and hat rendering", "Шлем и шляпа"),
    ("Optimizes armour rendering", "Броня"),
    ("Optimizes pants rendering", "Штаны"),
    ("Optimizes boot rendering", "Ботинки"),
    ("Optimizes back-slot attachment rendering", "Спина"),
    ("Optimizes left-arm attachment rendering", "Левая рука"),
    ("Optimizes right-arm attachment rendering", "Правая рука"),
    ("Optimizes left-leg attachment rendering", "Левая нога"),
    ("Optimizes right-leg attachment rendering", "Правая нога"),
    ("Optimizes attachments without a specific slot", "Слоты без привязки"),
    ("Write slot counters and diagnostic messages to RE_Kenshi_log.txt", "Счётчики слотов в RE_Kenshi_log.txt"),
    ("Hide distance", "Дистанция"),
    ("Restore default Attachment Optimization settings", "Сбросить настройки оптимизации"),
    ("Config reset to defaults.", "Настройки сброшены."),
    ("Reset defaults", "Сбросить"),
    ("Unknown error", "Ошибк
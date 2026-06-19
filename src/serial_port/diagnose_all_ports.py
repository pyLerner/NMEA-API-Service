import serial
import glob
import time

def check_port_data():
    # Список портов и стандартных скоростей
    ports = sorted(glob.glob('/dev/ttyS*'))
    baudrates = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]
    
    if not ports:
        print("Порты /dev/ttyS* не найдены.")
        return

    print(f"{'Порт':<12} | {'Baudrate':<10} | {'Статус данных'}")
    print("-" * 45)

    for port in ports:
        for baud in baudrates:
            try:
                # timeout=2 дает скрипту время подождать данные
                with serial.Serial(port, baud, timeout=2) as ser:
                    # Сбрасываем буферы перед проверкой
                    ser.reset_input_buffer()
                    
                    # Ждем некоторое время для накопления данных
                    time.sleep(0.5) 
                    if ser.in_waiting > 0:
                        # Читаем доступные байты
                        raw_data = ser.read(ser.in_waiting)
                        
                        # Декодируем в текст. 'replace' заменит битые символы на знак '?'
                        # strip() уберет лишние переносы строк (\n \r)
                        text_data = raw_data.decode('utf-8', errors='replace').strip()
                        
                        if text_data:
                            print(f"{port:<12} | {baud:<10} | ТЕКСТ: {text_data}")
                        else:
                            # Если данные были, но после strip() ничего не осталось (например, только пробелы)
                            print(f"{port:<12} | {baud:<10} | Получены непечатные символы")

                    #if ser.in_waiting > 0:
                    #    # Читаем доступные байты
                    #    data = ser.read(ser.in_waiting)
                    #    print(f"{port:<12} | {baud:<10} | ПОЛУЧЕНО: {data.hex()[:20]}...")
                    #else:
                    #    print(f"{port:<12} | {baud:<10} | Пусто (тишина)")
                    #    
            except (serial.SerialException, PermissionError) as e:
                # Пропускаем ошибки доступа, чтобы не загромождать вывод
                continue

if __name__ == "__main__":
    print("Начинаю сканирование (это может занять время)...")
    check_port_data()


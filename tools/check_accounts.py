from skills.trading.engine.account import get_account_summary
from skills.trading.engine.connection_manager import bridge_manager

if __name__ == '__main__':
    print('Bridge connected:', bridge_manager.get_status())
    print('\n--- Demo account summary ---')
    try:
        demo = get_account_summary(account_mode='demo')
        for k, v in demo.items():
            print(f'{k}: {v}')
    except Exception as e:
        print('Demo query error:', e)

    print('\n--- Real account summary ---')
    try:
        real = get_account_summary(account_mode='real')
        for k, v in real.items():
            print(f'{k}: {v}')
    except Exception as e:
        print('Real query error:', e)

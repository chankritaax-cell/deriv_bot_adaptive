import asyncio
import collections
import time
from modules.utils import log_print

class DerivStreamManager:
    """
    📡 Deriv Stream Manager (v4.0.3) - Anti-Spam Edition
    Handles real-time WebSocket subscriptions safely using Queue bridges and Watchdogs.
    [v4.0.3] Fixed infinite tight-loop log spam on websocket disconnect.
    """
    def __init__(self, api, asset):
        self.api = api
        self.asset = asset
        
        # State Variables
        self.latest_ticks = collections.deque(maxlen=10) # For Tick Velocity Guard
        self.current_candle = {}                        # Latest forming candle
        self.last_candle_epoch = None                  # Persist across reconnects
        self.candle_queue = asyncio.Queue()             # Queue for fully closed candles
        
        self._is_running = False
        self._tick_task = None
        self._candle_task = None
        self.api_failed = False  # Track fatal API connection drops
        
        log_print(f"📡 Stream Manager initialized for {self.asset}")

    async def start(self):
        await self.start_streams()

    async def start_streams(self):
        if self._is_running:
            return
            
        self._is_running = True
        log_print(f"🚀 Starting Real-time Streams for {self.asset}...")
        
        self._tick_task = asyncio.create_task(self._listen_ticks())
        self._candle_task = asyncio.create_task(self._listen_candles())

    async def _listen_ticks(self):
        """Tick stream with anti-spam error handling."""
        _last_error_msg = None  # Track last error to avoid duplicate logs

        while self._is_running:
            disposable = None
            try:
                try:
                    subscription = await asyncio.wait_for(
                        self.api.subscribe({'ticks': self.asset}),
                        timeout=10.0
                    )
                except asyncio.TimeoutError:
                    log_print("   WARN: Tick subscribe timeout. Retrying...")
                    _last_error_msg = None
                    await asyncio.sleep(2)
                    continue
                
                # 🛡️ Check for Server Error before subscribing
                if isinstance(subscription, dict) and 'error' in subscription:
                    err_msg = subscription['error'].get('message', 'Unknown')
                    if err_msg != _last_error_msg:
                        log_print(f"   ❌ Tick Subscription rejected: {err_msg}")
                        _last_error_msg = err_msg
                    await asyncio.sleep(5)
                    continue

                # Reset error tracker on successful subscription
                _last_error_msg = None

                # Bridge Rx Observable to Asyncio Queue
                q = asyncio.Queue()
                disposable = subscription.subscribe(
                    on_next=lambda x: q.put_nowait(x),
                    on_error=lambda e: q.put_nowait({'error': {'message': str(e)}})
                )
                
                while self._is_running:
                    # 🛡️ Watchdog: If no tick in 15 seconds, assume silent drop
                    response = await asyncio.wait_for(q.get(), timeout=15.0)
                    
                    if 'tick' in response:
                        tick = response['tick']
                        self.latest_ticks.append({
                            'price': float(tick['quote']),
                            'epoch': int(tick['epoch']),
                            'received_at': time.time()
                        })
                    elif 'error' in response:
                        err_msg = response['error'].get('message', 'Unknown')
                        if "no close frame received or sent" in err_msg.lower() or "connection closed" in err_msg.lower():
                            log_print(f"   💀 FATAL (Response): Tick Stream Dead: {err_msg}")
                            self.api_failed = True
                            self._is_running = False
                            break
                        
                        if err_msg != _last_error_msg:
                            log_print(f"   ❌ Tick Stream Error: {err_msg}. Reconnecting in 5s...")
                            _last_error_msg = err_msg
                        await asyncio.sleep(5)
                        break  # Break inner loop to reconnect
                        
            except asyncio.TimeoutError:
                log_print(f"   ⚠️ Tick Stream Timeout (Silent drop). Reconnecting...")
                _last_error_msg = None
                # Retry the outer subscription loop instead of exiting the listener.
                await asyncio.sleep(1)
                continue
            except Exception as e:
                err_msg = str(e)
                if "no close frame received or sent" in err_msg.lower() or "connection closed" in err_msg.lower() or "websockets.exceptions" in err_msg.lower():
                    log_print(f"   💀 FATAL: Tick Stream Connection Dead: {err_msg}")
                    self.api_failed = True
                    self._is_running = False
                    break
                
                if err_msg != _last_error_msg:
                    log_print(f"   ⚠️ Tick Stream Exception: {err_msg}. Retrying in 5s...")
                    _last_error_msg = err_msg
                await asyncio.sleep(5)  # Backoff before reconnect
            finally:
                # Dispose of zombie subscription to prevent memory leak
                if disposable:
                    try:
                        disposable.dispose()
                    except:
                        pass

    async def _listen_candles(self):
        """Candle stream with anti-spam error handling."""
        _last_error_msg = None  # Track last error to avoid duplicate logs

        while self._is_running:
            disposable = None
            try:
                try:
                    subscription = await asyncio.wait_for(
                        self.api.subscribe({
                            'ticks_history': self.asset,
                            'end': 'latest',
                            'style': 'candles',
                            'granularity': 60,
                            'subscribe': 1
                        }),
                        timeout=10.0
                    )
                except asyncio.TimeoutError:
                    log_print("   WARN: Candle subscribe timeout. Retrying...")
                    _last_error_msg = None
                    await asyncio.sleep(2)
                    continue
                
                # 🛡️ Check for Server Error before subscribing
                if isinstance(subscription, dict) and 'error' in subscription:
                    err_msg = subscription['error'].get('message', 'Unknown')
                    if err_msg != _last_error_msg:
                        log_print(f"   ❌ Candle Subscription rejected: {err_msg}")
                        _last_error_msg = err_msg
                    await asyncio.sleep(5)
                    continue

                # Reset error tracker on successful subscription
                _last_error_msg = None

                # Bridge Rx Observable to Asyncio Queue
                q = asyncio.Queue()
                disposable = subscription.subscribe(
                    on_next=lambda x: q.put_nowait(x),
                    on_error=lambda e: q.put_nowait({'error': {'message': str(e)}})
                )
                
                while self._is_running:
                    # 🛡️ Watchdog: Candles update every 2 seconds. Use 30s timeout
                    response = await asyncio.wait_for(q.get(), timeout=30.0)
                    
                    if 'ohlc' in response:
                        ohlc = response['ohlc']
                        current_epoch = int(ohlc['open_time'])
                        
                        candle_data = {
                            'epoch': current_epoch,
                            'open': float(ohlc['open']),
                            'high': float(ohlc['high']),
                            'low': float(ohlc['low']),
                            'close': float(ohlc['close'])
                        }
                        
                        # Detect Candle Close
                        if self.last_candle_epoch is not None and current_epoch > self.last_candle_epoch:
                            if self.current_candle:
                                await self.candle_queue.put(self.current_candle.copy())
 
                        self.current_candle = candle_data
                        self.last_candle_epoch = current_epoch
                        
                    elif 'error' in response:
                        err_msg = response['error'].get('message', 'Unknown')
                        if "no close frame received or sent" in err_msg.lower() or "connection closed" in err_msg.lower():
                            log_print(f"   💀 FATAL (Response): Candle Stream Dead: {err_msg}")
                            self.api_failed = True
                            self._is_running = False
                            break
                            
                        if err_msg != _last_error_msg:
                            log_print(f"   ❌ Candle Stream Error: {err_msg}. Reconnecting in 5s...")
                            _last_error_msg = err_msg
                        await asyncio.sleep(5)
                        break  # Break inner loop to reconnect
                        
            except asyncio.TimeoutError:
                log_print(f"   ⚠️ Candle Stream Timeout (Silent drop). Reconnecting...")
                _last_error_msg = None
                # Retry the outer subscription loop instead of exiting the listener.
                await asyncio.sleep(1)
                continue
            except Exception as e:
                err_msg = str(e)
                if "no close frame received or sent" in err_msg.lower() or "connection closed" in err_msg.lower() or "websockets.exceptions" in err_msg.lower():
                    log_print(f"   💀 FATAL: Candle Stream Connection Dead: {err_msg}")
                    self.api_failed = True
                    self._is_running = False
                    break
                
                if err_msg != _last_error_msg:
                    log_print(f"   ⚠️ Candle Stream Exception: {err_msg}. Retrying in 5s...")
                    _last_error_msg = err_msg
                await asyncio.sleep(5)  # Backoff before reconnect
            finally:
                # Dispose of zombie subscription to prevent memory leak
                if disposable:
                    try:
                        disposable.dispose()
                    except:
                        pass

    async def stop(self):
        self._is_running = False
        for task in [self._tick_task, self._candle_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._tick_task = None
        self._candle_task = None
        log_print(f"🛑 Streams stopped for {self.asset}")
import logging
import json
import time
import requests
import struct
import base64
import uuid
import threading
import websocket
from datetime import datetime

_LOGGER = logging.getLogger(__name__)

class KiwikClient:
    def __init__(self, uid, password, device_id, token_data=None, on_event_callback=None):
        self.uid = uid
        self.password = password
        self.device_id = device_id
        self.base_url = "https://go.kiwik.cn"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-kiwik-client-id": "igxknDUbISY3XAcBYJT9SIegd31sPu7B",
            "Origin": "https://go.kiwik.cn"
        })
        
        self.access_token = token_data.get("access_token") if token_data else None
        self.refresh_token = token_data.get("refresh_token") if token_data else None
        
        if self.access_token:
            self.session.headers["Authorization"] = f"Bearer {self.access_token}"
            
        self.ws = None
        self.stop_heartbeat = False
        self.running = False
        self.callbacks = []

    def set_callback(self, callback):
        # 兼容旧方法
        self.add_sensor_callback(callback)

    def add_sensor_callback(self, callback):
        if callback not in self.callbacks:
            self.callbacks.append(callback)

    def encode_array(self, cmd, data=[]):
        """编码命令和数据 (Cmd: 2bytes, Data: bytes) -> Base64URL"""
        cmd_bytes = struct.pack(">H", cmd)
        if isinstance(data, list):
            data_bytes = bytes(data)
        else:
            data_bytes = data
        full_bytes = cmd_bytes + data_bytes
        latin1_str = full_bytes.decode('latin-1')
        b64_bytes = base64.b64encode(latin1_str.encode('latin-1'))
        b64_str = b64_bytes.decode('utf-8')
        encoded = b64_str.replace("+", "-").replace("/", "_")
        return encoded

    def login(self):
        """完整的 OAuth2 登录流程"""
        # 0. 尝试使用 refresh_token 刷新
        if self.refresh_token:
            _LOGGER.info("尝试使用 Refresh Token 刷新...")
            if self._refresh_access_token():
                return True
            _LOGGER.warning("刷新 Token 失败，将执行完整登录流程")
            
        try:
            session_token = self._get_session_token()
            if not session_token:
                return False
            
            auth_code = self._get_auth_code(session_token)
            if not auth_code:
                return False
            
            token_data = self._exchange_token(auth_code)
            if not token_data:
                return False
            
            return True
        except Exception as e:
            _LOGGER.error(f"登录流程异常: {e}")
            return False

    def _get_session_token(self):
        url = f"{self.base_url}/restapi/users/{self.uid}/mfa/tokens"
        payload = {
            "auth_type": "secure_password",
            "credential": self.password
        }
        resp = self.session.post(url, json=payload)
        if resp.status_code in [200, 201]:
            return resp.json().get("access_token")
        _LOGGER.error(f"获取会话令牌失败: {resp.status_code}")
        return None

    def _get_auth_code(self, session_token):
        url = "https://account.kiwik.cn/auth/realms/kiwik/oauth/authorize"
        params = {
            "response_type": "code",
            "client_id": "igxknDUbISY3XAcBYJT9SIegd31sPu7B",
            "session_token": session_token,
            "redirect_uri": "https://go.kiwik.cn/app/woa/oauth/callback",
            "state": "antigravity"
        }
        resp = self.session.get(url, params=params, allow_redirects=False)
        if resp.status_code == 302:
            location = resp.headers.get("Location", "")
            if "code=" in location:
                return location.split("code=")[1].split("&")[0]
        return None

    def _exchange_token(self, auth_code):
        url = "https://account.kiwik.cn/auth/realms/kiwik/oauth/token"
        payload = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "client_id": "igxknDUbISY3XAcBYJT9SIegd31sPu7B",
            "redirect_uri": "https://go.kiwik.cn/app/woa/oauth/callback"
        }
        resp = self.session.post(url, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
        if resp.status_code == 200:
            data = resp.json()
            self.access_token = data.get("access_token")
            self.refresh_token = data.get("refresh_token")
            if self.access_token:
                self.session.headers["Authorization"] = f"Bearer {self.access_token}"
            return data
        return None

    def _refresh_access_token(self):
        url = "https://account.kiwik.cn/auth/realms/kiwik/oauth/token"
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": "igxknDUbISY3XAcBYJT9SIegd31sPu7B"
        }
        try:
            resp = self.session.post(url, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
            if resp.status_code == 200:
                data = resp.json()
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")
                self.session.headers["Authorization"] = f"Bearer {self.access_token}"
                return True
            return False
        except Exception:
            return False

    def start(self):
        """启动后台监控"""
        if self.running:
            return
        
        if not self.access_token:
            if not self.login():
                _LOGGER.error("无法启动监控：登录失败")
                return

        self.running = True
        self.conn_thread = threading.Thread(target=self._run_ws_forever)
        self.conn_thread.daemon = True
        self.conn_thread.start()
        _LOGGER.info("Kiwik 客户端后台线程已启动")

    def stop(self):
        """停止监控"""
        self.running = False
        self.stop_heartbeat = True
        if self.ws:
            self.ws.close()

    def _run_ws_forever(self):
        while self.running:
            try:
                ws_url = f"wss://wsapi.kiwiot.com/?access_token={self.access_token}"
                self.ws = websocket.WebSocketApp(
                    ws_url,
                    on_open=self._on_ws_open,
                    on_message=self._on_ws_message,
                    on_error=self._on_ws_error,
                    on_close=self._on_ws_close
                )
                self.ws.run_forever(ping_interval=None)
                
                if self.running:
                    _LOGGER.warning("WS断开，5秒后重连...")
                    time.sleep(5)
                    # 尝试刷新 Token
                    if self.refresh_token:
                        self._refresh_access_token()
            except Exception as e:
                _LOGGER.error(f"WS 循环异常: {e}")
                time.sleep(10)

    def _on_ws_open(self, ws):
        _LOGGER.info("WebSocket 连接建立")
        self.stop_heartbeat = False
        t = threading.Thread(target=self._heartbeat_loop)
        t.daemon = True
        t.start()
        
        # 通知连接恢复
        for cb in self.callbacks:
            cb("CONNECTED", {})

    def _on_ws_close(self, ws, *args):
        _LOGGER.info("WebSocket 连接关闭")
        self.stop_heartbeat = True

    def _on_ws_error(self, ws, error):
        _LOGGER.error(f"WebSocket 错误: {error}")

    def _on_ws_message(self, ws, message):
        try:
            msg = json.loads(message)
            header = msg.get("header", {})
            name = header.get("name")
            
            if name == "Pong":
                return

            if name == "EventNotify":
                payload = msg.get("payload", {})
                _LOGGER.debug(f"EventNotify: {payload}")
                event_name = str(payload.get("event", "")).upper()
                
                for cb in self.callbacks:
                    # 传递原始 payload
                    cb("EVENT", payload)
                    
                    # 专门的状态更新
                    if "UNLOCK" in event_name or "OPEN" in event_name:
                        cb("STATE_UPDATE", "UNLOCKED")

            elif name == "CtrlResponse":
                _LOGGER.info(f"控制响应: {message}")
            elif name == "ErrorResponse":
                _LOGGER.error(f"错误响应: {message}")
                
        except Exception as e:
            _LOGGER.error(f"处理消息失败: {e}")

    def _heartbeat_loop(self):
        while not self.stop_heartbeat and self.running:
            try:
                if self.ws and self.ws.sock and self.ws.sock.connected:
                    mid = str(uuid.uuid4())
                    ping = {
                        "header": {
                            "namespace": "Iot.Application",
                            "name": "Ping",
                            "messageId": mid,
                            "payloadVersion": 1
                        },
                        "payload": {}
                    }
                    self.ws.send(json.dumps(ping))
                else:
                    break
            except Exception:
                break
            time.sleep(30)

    def unlock(self):
        """发送开锁指令"""
        secure_token = self._get_session_token()
        if not secure_token:
            _LOGGER.error("无法获取 Secure Token")
            return False

        if not self.ws or not self.ws.sock or not self.ws.sock.connected:
            _LOGGER.error("WS 未连接")
            return False

        try:
            uid_bytes = self.uid.encode('utf-8')
            S = len(uid_bytes)
            # CMDCACHE (5638) -> RMUNLK (5132) logic
            D = [S+2, 1, S] + list(uid_bytes)
            C = [0, S+11, 0, 0, 0, 10, 0, S+5, 0x14, 0x0C] + D
            encoded_data = self.encode_array(5638, C) 
            
            mid = str(uuid.uuid4())
            payload = {
                "header": {
                    "namespace": "Iot.Device",
                    "name": "Ctrl",
                    "messageId": mid,
                    "payloadVersion": 1,
                    "secureToken": secure_token
                },
                "payload": {
                    "did": self.device_id,
                    "data": encoded_data
                }
            }
            self.ws.send(json.dumps(payload))
            _LOGGER.info("开锁指令已发送")
            
            # 乐观更新状态
            for cb in self.callbacks:
                cb("STATE_UPDATE", "UNLOCKED")
                
            return True
        except Exception as e:
            _LOGGER.error(f"开锁异常: {e}")
            return False

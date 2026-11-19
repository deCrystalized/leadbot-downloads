/* 2.0: в расширении нет ни одного ключа. ИИ, карты, Telegram и общая память — на сервере «мозг»:
   расширение знает только его адрес, а личный токен владельца вводится в настройках (chrome.storage.local, brainToken).
   brainUrl вписывается при развёртывании мозга (адрес облачной функции lead-centre-brain). */
const CONFIG = {
  "brainUrl": "https://72-56-99-103.sslip.io/brain",
  "leadchatHosts": [
    "188-225-34-82.sslip.io"
  ]
};

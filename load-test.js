// load-test.js
import http from 'k6/http';
import { check, sleep } from 'k6';

// 設定虛擬使用者數量與時間
export const options = {
    vus: 50,           // 模擬併發使用者
    duration: '30s',   // 持續30 秒
};

// 每個虛擬使用者會不斷重複執行這裡
export default function () {
    const url = 'http://localhost:4000/chat/completions';
    const payload = JSON.stringify({
    model: "qwen:0.5b", 
        messages: [{"role": "user", "content": "hello, could you introduce youself?"}]
    });

    const params = {
        headers: {
            'content-type': 'application/json',
            'authorization': 'Bearer sk-eEHl96TgzivdH_8h-wPLzQ', 
        },
    };

    const res = http.post(url, payload, params);

    check(res, {
        '✅ 請求成功 (status 200)': (r) => r.status === 200,
        '* 觸發限流 (status 429)': (r) => r.status === 429,
        '* 權限錯誤 (status 401)': (r) => r.status === 401,
        '* 系統崩潰 (status 500)': (r) => r.status === 500,
    });

    sleep(1); 
}

// load-test.js
import http from 'k6/http';
import { check, sleep } from 'k6';
// 引入 k6 內建的隨機字串產生器
import { randomString } from 'https://jslib.k6.io/k6-utils/1.2.0/index.js';

export const options = {
    vus: 6,           
    duration: '30s', 
};

// 每個虛擬使用者會不斷重複執行這裡
export default function () {
    const url = 'http://localhost:4000/chat/completions';
    
    //  動態產生一個 8 位的隨機亂碼
    const randomStr = randomString(8);

    const payload = JSON.stringify({
        model: "qwen:0.5b", 
        //  將隨機亂碼塞入 prompt，強迫打破 Redis 快取，流量直穿底層 GPU/CPU
        messages: [{"role": "user", "content": `hello, could you introduce yourself? [TraceID: ${randomStr}]`}]
    });

    const params = {
        headers: {
            'content-type': 'application/json',
            'authorization': 'Bearer sk-eEHl96TgzivdH_8h-wPLzQ', 
        },
        //  針對長文生成與 CPU 運算，將 Timeout 拉長，避免 k6 單方面斷線
        timeout: '120s', 
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

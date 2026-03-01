// 429-load-test.js 
import http from 'k6/http'; 
import { check } from 'k6';

export const options = { 
    vus: 50,          
    duration: '20s',  
}; 

export default function () { 
    const url = 'http://localhost:4000/chat/completions'; 
    const payload = JSON.stringify({ 
        model: "qwen:0.5b",  
        messages: [{"role": "user", "content": "hello, say something."}] 
    }); 

    const params = { 
        headers: { 
            'content-type': 'application/json', 
            'authorization': 'Bearer sk-eEHl96TgzivdH_8h-wPLzQ',  
        }, 
        timeout: '30s', // 防止網關還沒回傳 429 k6 就先放棄
    }; 

    const res = http.post(url, payload, params); 

    check(res, { 
        '✅ 請求成功 (status 200)': (r) => r.status === 200, 
        '🔥 觸發限流 (status 429)': (r) => r.status === 429, 
        '❌ 權限錯誤 (status 401)': (r) => r.status === 401, 
        '💥 系統崩潰 (status 500)': (r) => r.status === 500, 
    }); 

}

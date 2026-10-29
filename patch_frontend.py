import os
import shutil

JS_PATH = os.path.join("static_frontend", "assets", "index-BbdRGwz5.js")
BAK_PATH = JS_PATH + ".bak"

OLD_AUTH_AND_FETCH = (
    'function Wn(){let[e,t]=(0,_.useState)(!0),[n,r]=(0,_.useState)(``),[i,a]=(0,_.useState)(``),[o,s]=(0,_.useState)({}),c=vt();'
    'function l(e){e.preventDefault(),s({});let t=!1,o={};n.trim()||(o.login=`Неверный формат (пустая строка)`,t=!0),i.trim()||(o.password=`Неверный формат`,t=!0),t?(s(o),n.trim()||r(``),i.trim()||a(``)):c(`/start`)}'
    'function u(){t(!e),s({}),r(``),a(``)}'
    'return(0,M.jsx)(`div`,{className:`screen`,children:(0,M.jsxs)(`div`,{className:`stage`,children:[(0,M.jsx)(Hn,{variant:`start`}),(0,M.jsxs)(`div`,{className:`auth-box`,children:[(0,M.jsx)(`h2`,{className:`auth-title`,children:e?`Авторизация`:`Регистрация`}),(0,M.jsxs)(`form`,{onSubmit:l,className:`auth-form`,children:[(0,M.jsxs)(`div`,{className:`auth-row`,children:[(0,M.jsx)(`label`,{children:`Логин:`}),(0,M.jsx)(`input`,{type:`text`,value:n,onChange:e=>r(e.target.value),placeholder:o.login||``,className:o.login?`input-error`:``})]}),(0,M.jsxs)(`div`,{className:`auth-row`,children:[(0,M.jsx)(`label`,{children:`Пароль:`}),(0,M.jsx)(`input`,{type:`password`,value:i,onChange:e=>a(e.target.value),placeholder:o.password||``,className:o.password?`input-error`:``})]}),(0,M.jsx)(`button`,{type:`submit`,className:`auth-submit`,children:e?`Войти`:`Зарегистрироваться`})]}),(0,M.jsx)(`button`,{type:`button`,className:`auth-switch`,onClick:u,children:e?`Нет аккаунта...`:`Уже есть аккаунт...`})]}),(0,M.jsx)(`p`,{className:`start-caption`,children:`Я всё помню...`}),(0,M.jsx)(`img`,{src:Un,alt:``,className:`crow crow--start`})]})})}'
    'function Gn(){return(0,M.jsx)(`div`,{className:`screen`,children:(0,M.jsxs)(`div`,{className:`stage`,children:[(0,M.jsx)(Hn,{variant:`start`}),(0,M.jsx)(kn,{to:`/`,style:{position:`absolute`,top:`calc(var(--u) * 16)`,right:`calc(var(--u) * 16)`,fontSize:`calc(var(--u) * 18)`,textDecoration:`underline`,textDecorationThickness:`calc(var(--u) * 2)`,color:`var(--ink)`},title:`Выйти из профиля`,children:`[ выход ]`}),(0,M.jsx)(kn,{to:`/menu`,className:`start-button`,children:(0,M.jsx)(`span`,{children:`START`})}),(0,M.jsx)(`p`,{className:`start-caption`,children:`Я всё помню...`}),(0,M.jsx)(`img`,{src:Un,alt:``,className:`crow crow--start`})]})})}'
    'var Kn=``,qn=e=>`${Kn}${e}`;'
    'async function Jn(e,t){let n=await fetch(qn(e),t);if(!n.ok)throw Error(`Сервер ответил ошибкой ${n.status}`);let r=await n.text(),i=r?JSON.parse(r):void 0;return Yn(i),i}'
)

NEW_AUTH_AND_FETCH = """function checkVoronaPassword(pwd,login){
  const issues=[];
  if(pwd.length<8)issues.push(`минимум 8 символов (сейчас ${pwd.length})`);
  if(pwd.includes(` `))issues.push(`уберите пробелы`);
  if(!/[A-ZА-ЯЁ]/.test(pwd))issues.push(`нужна заглавная буква`);
  if(!/[a-zа-яё]/.test(pwd))issues.push(`нужна строчная буква`);
  if(!/\\d/.test(pwd))issues.push(`нужна цифра`);
  if(!/[!@#$%^&*()_+\\-=\\[\\]{};:'",.<>/?\\\\|`~]/.test(pwd))issues.push(`нужен спецсимвол (!@#$% и т.д.)`);
  if(login && pwd.toLowerCase()===login.trim().toLowerCase())issues.push(`не должен совпадать с логином`);
  return issues.length?`Исправьте пароль: `+issues.join(`, `):null;
}
function Wn(){
  let[e,t]=(0,_.useState)(!0),[n,r]=(0,_.useState)(``),[i,a]=(0,_.useState)(``),[o,s]=(0,_.useState)({}),[busy,setBusy]=(0,_.useState)(!1),c=vt();
  (0,_.useEffect)(()=>{
    const tok=localStorage.getItem(`vorona_token`);
    if(!tok)return;
    fetch(`/api/auth/me`,{headers:{Authorization:`Bearer ${tok}`}})
      .then(res=>{if(res.ok)c(`/start`);else{localStorage.removeItem(`vorona_token`);localStorage.removeItem(`vorona_username`);}})
      .catch(()=>{});
  },[c]);
  async function l(ev){
    ev.preventDefault();
    if(busy)return;
    s({});
    let hasErr=!1,errObj={};
    if(!n.trim()){errObj.login=`Введите логин`;hasErr=!0;}
    else if(n.trim().length<2){errObj.login=`Логин: минимум 2 символа`;hasErr=!0;}
    if(!i){errObj.password=`Введите пароль`;hasErr=!0;}
    else if(!e){
      const pwdMsg=checkVoronaPassword(i,n);
      if(pwdMsg){errObj.password=pwdMsg;hasErr=!0;}
    }
    if(hasErr){
      s(errObj);
      if(errObj.login)r(``);
      if(errObj.password)a(``);
      return;
    }
    setBusy(!0);
    try{
      const url=e?`/api/auth/login`:`/api/auth/register`;
      const res=await fetch(url,{
        method:`POST`,
        headers:{"Content-Type":`application/json`},
        body:JSON.stringify({username:n.trim(),password:i})
      });
      const data=await res.json().catch(()=>({}));
      if(!res.ok){
        const detail=data.detail||`Ошибка авторизации`;
        if(res.status===409 || detail.toLowerCase().includes(`логин`)){
          s({login:detail});
          r(``);
        }else{
          s({password:detail});
          a(``);
        }
        return;
      }
      localStorage.setItem(`vorona_token`,data.token);
      localStorage.setItem(`vorona_username`,data.user?.username||n.trim());
      c(`/start`);
    }catch(err){
      s({login:`Сервер недоступен`});
      r(``);
    }finally{
      setBusy(!1);
    }
  }
  function u(){t(!e),s({}),r(``),a(``)}
  const errBanner=o.password||o.login||``;
  return(0,M.jsx)(`div`,{className:`screen`,children:(0,M.jsxs)(`div`,{className:`stage`,children:[(0,M.jsx)(Hn,{variant:`start`}),(0,M.jsxs)(`div`,{className:`auth-box`,children:[(0,M.jsx)(`h2`,{className:`auth-title`,children:e?`Авторизация`:`Регистрация`}),(0,M.jsxs)(`form`,{onSubmit:l,className:`auth-form`,children:[(0,M.jsxs)(`div`,{className:`auth-row`,children:[(0,M.jsx)(`label`,{children:`Логин:`}),(0,M.jsx)(`input`,{type:`text`,value:n,onChange:ev=>{r(ev.target.value);if(o.login)s({...o,login:``});},placeholder:o.login||``,className:o.login?`input-error`:``})]}),(0,M.jsxs)(`div`,{className:`auth-row`,children:[(0,M.jsx)(`label`,{children:`Пароль:`}),(0,M.jsx)(`input`,{type:`password`,value:i,onChange:ev=>{a(ev.target.value);if(o.password)s({...o,password:``});},placeholder:o.password?`Не соответствует требованиям`:``,className:o.password?`input-error`:``})]}),errBanner&&(0,M.jsx)(`div`,{style:{color:`#b00020`,fontSize:`calc(var(--u) * 11)`,lineHeight:`1.25`,textAlign:`center`,padding:`calc(var(--u) * 4) calc(var(--u) * 6)`,border:`1.5px solid #b00020`,background:`rgba(176,0,32,0.06)`},children:errBanner}),(0,M.jsx)(`button`,{type:`submit`,disabled:busy,className:`auth-submit`,children:e?`Войти`:`Зарегистрироваться`})]}),(0,M.jsx)(`button`,{type:`button`,className:`auth-switch`,onClick:u,children:e?`Нет аккаунта...`:`Уже есть аккаунт...`})]}),(0,M.jsx)(`p`,{className:`start-caption`,children:`Я всё помню...`}),(0,M.jsx)(`img`,{src:Un,alt:``,className:`crow crow--start`})]})});
}
function Gn(){
  const c=vt();
  const username=localStorage.getItem(`vorona_username`)||``;
  (0,_.useEffect)(()=>{
    if(!localStorage.getItem(`vorona_token`))c(`/`);
  },[c]);
  function handleLogout(){
    localStorage.removeItem(`vorona_token`);
    localStorage.removeItem(`vorona_username`);
  }
  return(0,M.jsx)(`div`,{className:`screen`,children:(0,M.jsxs)(`div`,{className:`stage`,children:[(0,M.jsx)(Hn,{variant:`start`}),(0,M.jsx)(kn,{to:`/`,onClick:handleLogout,style:{position:`absolute`,top:`calc(var(--u) * 16)`,right:`calc(var(--u) * 16)`,fontSize:`calc(var(--u) * 18)`,textDecoration:`underline`,textDecorationThickness:`calc(var(--u) * 2)`,color:`var(--ink)`},title:`Выйти из профиля`,children:username?`[ ${username} — выход ]`:`[ выход ]`}),(0,M.jsx)(kn,{to:`/menu`,className:`start-button`,children:(0,M.jsx)(`span`,{children:`START`})}),(0,M.jsx)(`p`,{className:`start-caption`,children:`Я всё помню...`}),(0,M.jsx)(`img`,{src:Un,alt:``,className:`crow crow--start`})]})});
}
var Kn=``,qn=e=>`${Kn}${e}`;
async function Jn(e,t={}){
  const tok=localStorage.getItem(`vorona_token`)||``;
  const headers=new Headers(t.headers||{});
  if(tok && !headers.has(`Authorization`)){
    headers.set(`Authorization`,`Bearer ${tok}`);
  }
  let n=await fetch(qn(e),{...t,headers});
  if(n.status===401){
    localStorage.removeItem(`vorona_token`);
    localStorage.removeItem(`vorona_username`);
    if(!window.location.hash.endsWith(`#/`)){
      window.location.hash=`#/`;
    }
    throw Error(`Необходима авторизация`);
  }
  if(!n.ok)throw Error(`Сервер ответил ошибкой ${n.status}`);
  let r=await n.text(),i=r?JSON.parse(r):void 0;
  return Yn(i),i;
}"""

OLD_NOTIF_POLL = "async function Dr(){return(await Jn(`/api/notifications`))?.notifications??[]}"
NEW_NOTIF_POLL = "async function Dr(){if(!localStorage.getItem(`vorona_token`))return[];return(await Jn(`/api/notifications`))?.notifications??[]}"


def main():
    if not os.path.exists(JS_PATH):
        print(f"❌ Файл не найден: {JS_PATH}")
        return

    if os.path.exists(BAK_PATH):
        shutil.copyfile(BAK_PATH, JS_PATH)

    with open(JS_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    if OLD_AUTH_AND_FETCH in content and not os.path.exists(BAK_PATH):
        shutil.copyfile(JS_PATH, BAK_PATH)

    if OLD_AUTH_AND_FETCH not in content:
        print("ℹ️ Не удалось найти исходный блок в JS-файле. Проверьте наличие резервной копии .bak.")
        return

    content = content.replace(OLD_AUTH_AND_FETCH, NEW_AUTH_AND_FETCH)
    content = content.replace(OLD_NOTIF_POLL, NEW_NOTIF_POLL)

    with open(JS_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print("✅ Проверка сложности пароля и подсказки при регистрации успешно добавлены!")


if __name__ == "__main__":
    main()

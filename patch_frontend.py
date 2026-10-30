import os
import re
import shutil

ASSETS_DIR = os.path.join("static_frontend", "assets")
INDEX_HTML_PATH = os.path.join("static_frontend", "index.html")
TARGET_JS_NAME = "index-DfO6stMJ.js"
JS_PATH = os.path.join(ASSETS_DIR, TARGET_JS_NAME)
BAK_PATH = JS_PATH + ".bak"

# Точный фрагмент из нового файла index-DfO6stMJ.js
OLD_AUTH_AND_FETCH = (
    'function Wn(){let[e,t]=(0,_.useState)(!0),[n,r]=(0,_.useState)(``),[i,a]=(0,_.useState)(``),[o,s]=(0,_.useState)({}),c=vt();'
    'function l(e){e.preventDefault(),s({});let t=!1,o={};n.trim()||(o.login=`Неверный формат (пустая строка)`,t=!0),i.trim()||(o.password=`Неверный формат`,t=!0),n.trim()===`admin`&&i.trim()===`wrong`&&(o.global=`Ошибка авторизации`,t=!0),t?(s(o),n.trim()||r(``),i.trim()||a(``)):c(`/start`)}'
    'function u(){t(!e),s({}),r(``),a(``)}'
    'return(0,M.jsx)(`div`,{className:`screen`,children:(0,M.jsxs)(`div`,{className:`stage`,children:[(0,M.jsx)(Hn,{variant:`start`}),(0,M.jsxs)(`div`,{className:`auth-box`,children:[(0,M.jsx)(`h2`,{className:`auth-title`,children:e?`Авторизация`:`Регистрация`}),(0,M.jsxs)(`form`,{onSubmit:l,className:`auth-form`,children:[(0,M.jsxs)(`div`,{className:`auth-row`,children:[(0,M.jsx)(`label`,{children:`Логин:`}),(0,M.jsx)(`input`,{type:`text`,value:n,onChange:e=>r(e.target.value),placeholder:o.login||``,className:o.login?`input-error`:``})]}),(0,M.jsxs)(`div`,{className:`auth-row`,children:[(0,M.jsx)(`label`,{children:`Пароль:`}),(0,M.jsx)(`input`,{type:`password`,value:i,onChange:e=>a(e.target.value),placeholder:o.password||``,className:o.password?`input-error`:``})]}),o.global&&(0,M.jsx)(`div`,{className:`auth-error-global`,children:o.global}),(0,M.jsx)(`button`,{type:`submit`,className:`auth-submit`,children:e?`Войти`:`Зарегистрироваться`})]}),(0,M.jsx)(`button`,{type:`button`,className:`auth-switch`,onClick:u,children:e?`Нет аккаунта...`:`Уже есть аккаунт...`})]}),(0,M.jsx)(`p`,{className:`start-caption`,children:`Я всё помню...`}),(0,M.jsx)(`img`,{src:Un,alt:``,className:`crow crow--start`})]})})}'
    'function Gn(){return(0,M.jsx)(`div`,{className:`screen`,children:(0,M.jsxs)(`div`,{className:`stage`,children:[(0,M.jsx)(Hn,{variant:`start`}),(0,M.jsx)(kn,{to:`/`,style:{position:`absolute`,top:`calc(var(--u) * 16)`,right:`calc(var(--u) * 16)`,fontSize:`calc(var(--u) * 18)`,textDecoration:`underline`,textDecorationThickness:`calc(var(--u) * 2)`,color:`var(--ink)`},title:`Выйти из профиля`,children:`[ выход ]`}),(0,M.jsx)(kn,{to:`/menu`,className:`start-button`,children:(0,M.jsx)(`span`,{children:`START`})}),(0,M.jsx)(`p`,{className:`start-caption`,children:`Я всё помню...`}),(0,M.jsx)(`img`,{src:Un,alt:``,className:`crow crow--start`})]})})}'
    'var Kn=``,qn=e=>`${Kn}${e}`;'
    'async function Jn(e,t){let n=await fetch(qn(e),t);if(!n.ok)throw Error(`Сервер ответил ошибкой ${n.status}`);let r=await n.text(),i=r?JSON.parse(r):void 0;return Yn(i),i}'
)

NEW_AUTH_AND_FETCH = """function checkVoronaPassword(pwd,login){
  const issues=[];
  if(pwd.length<8)issues.push(`минимум 8 символов (сейчас ${pwd.length})`);
  if(pwd.includes(` `))issues.push(`без пробелов`);
  if(!/[A-ZА-ЯЁ]/.test(pwd))issues.push(`заглавная буква`);
  if(!/[a-zа-яё]/.test(pwd))issues.push(`строчная буква`);
  if(!/\\d/.test(pwd))issues.push(`цифра`);
  if(!/[!@#$%^&*()_+\\-=\\[\\]{};:'",.<>/?\\\\|`~]/.test(pwd))issues.push(`спецсимвол (!@#$% и т.д.)`);
  if(login && pwd.toLowerCase()===login.trim().toLowerCase())issues.push(`не должен совпадать с логином`);
  return issues.length?`Исправьте пароль: `+issues.join(`, `):null;
}
function Wn(){
  let[e,t]=(0,_.useState)(!0),[n,r]=(0,_.useState)(``),[i,a]=(0,_.useState)(``),[o,s]=(0,_.useState)({}),[busy,setBusy]=(0,_.useState)(!1),c=vt();
  const loginRef=(0,_.useRef)(null),passRef=(0,_.useRef)(null);
  (0,_.useEffect)(()=>{
    const tok=localStorage.getItem(`vorona_token`);
    if(!tok)return;
    fetch(`/api/auth/me`,{headers:{Authorization:`Bearer ${tok}`}})
      .then(res=>{if(res.ok)c(`/start`);else{localStorage.removeItem(`vorona_token`);localStorage.removeItem(`vorona_username`);}})
      .catch(()=>{});
  },[c]);
  function clearErrAndFocus(target){
    if(o.login||o.password||o.global){
      s({});
    }
    setTimeout(()=>{
      if(target===`login`)loginRef.current?.focus();
      else if(target===`password`)passRef.current?.focus();
    },0);
  }
  async function l(ev){
    ev.preventDefault();
    if(busy)return;
    s({});
    let hasErr=!1,errObj={};
    if(!n.trim()){errObj.login=`Неверный формат (пустая строка)`;errObj._target=`login`;hasErr=!0;}
    else if(n.trim().length<2){errObj.login=`Минимум 2 символа`;errObj._target=`login`;hasErr=!0;}
    if(!i.trim()){errObj.password=`Неверный формат`;if(!errObj._target)errObj._target=`password`;hasErr=!0;}
    else if(!e){
      const pwdMsg=checkVoronaPassword(i,n);
      if(pwdMsg){errObj.password=`Слабый пароль`;errObj.global=pwdMsg;errObj._target=`password`;hasErr=!0;}
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
        if(res.status===409){
          s({login:detail,global:detail,_target:`login`});
          r(``);
        }else if(res.status===401){
          s({password:`Неверный пароль`,global:detail,_target:`password`});
          a(``);
        }else{
          s({password:`Исправьте пароль`,global:detail,_target:`password`});
          a(``);
        }
        return;
      }
      localStorage.setItem(`vorona_token`,data.token);
      localStorage.setItem(`vorona_username`,data.user?.username||n.trim());
      c(`/start`);
    }catch(err){
      s({global:`Сервер недоступен`,_target:`login`});
    }finally{
      setBusy(!1);
    }
  }
  function u(){t(!e),s({}),r(``),a(``)}
  return(0,M.jsx)(`div`,{className:`screen`,children:(0,M.jsxs)(`div`,{className:`stage`,children:[(0,M.jsx)(Hn,{variant:`start`}),(0,M.jsxs)(`div`,{className:`auth-box`,children:[(0,M.jsx)(`h2`,{className:`auth-title`,children:e?`Авторизация`:`Регистрация`}),(0,M.jsxs)(`form`,{onSubmit:l,className:`auth-form`,children:[(0,M.jsxs)(`div`,{className:`auth-row`,onMouseDown:()=>clearErrAndFocus(`login`),children:[(0,M.jsx)(`label`,{children:`Логин:`}),(0,M.jsx)(`input`,{ref:loginRef,type:`text`,value:n,onFocus:()=>{if(o.login||o.global)s({});},onClick:()=>{if(o.login||o.global)s({});},onChange:ev=>{if(o.login||o.global)s({});r(ev.target.value);},placeholder:o.login||``,className:o.login?`input-error`:``})]}),(0,M.jsxs)(`div`,{className:`auth-row`,onMouseDown:()=>clearErrAndFocus(`password`),children:[(0,M.jsx)(`label`,{children:`Пароль:`}),(0,M.jsx)(`input`,{ref:passRef,type:`password`,value:i,onFocus:()=>{if(o.password||o.global)s({});},onClick:()=>{if(o.password||o.global)s({});},onChange:ev=>{if(o.password||o.global)s({});a(ev.target.value);},placeholder:o.password||``,className:o.password?`input-error`:``})]}),o.global&&(0,M.jsx)(`div`,{className:`auth-error-global`,style:{cursor:`text`},onMouseDown:ev=>{ev.preventDefault();clearErrAndFocus(o._target||`password`);},onClick:()=>clearErrAndFocus(o._target||`password`),children:o.global}),(0,M.jsx)(`button`,{type:`submit`,disabled:busy,className:`auth-submit`,children:e?`Войти`:`Зарегистрироваться`})]}),(0,M.jsx)(`button`,{type:`button`,className:`auth-switch`,onClick:u,children:e?`Нет аккаунта...`:`Уже есть аккаунт...`})]}),(0,M.jsx)(`p`,{className:`start-caption`,children:`Я всё помню...`}),(0,M.jsx)(`img`,{src:Un,alt:``,className:`crow crow--start`})]})});
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


def sync_index_html_script_tag():
    """Обновляет ссылку на index-DfO6stMJ.js внутри static_frontend/index.html, если там старый хеш."""
    if not os.path.exists(INDEX_HTML_PATH):
        return
    with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    new_html = re.sub(r"/assets/index-[A-Za-z0-9_-]+\.js", f"/assets/{TARGET_JS_NAME}", html)
    if new_html != html:
        with open(INDEX_HTML_PATH, "w", encoding="utf-8") as f:
            f.write(new_html)
        print(f"✅ Обновлена ссылка в index.html -> /assets/{TARGET_JS_NAME}")


def main():
    if not os.path.exists(JS_PATH):
        print(f"❌ Файл не найден: {JS_PATH}")
        print("Положите index-DfO6stMJ.js в папку static_frontend/assets/")
        return

    sync_index_html_script_tag()

    if os.path.exists(BAK_PATH):
        shutil.copyfile(BAK_PATH, JS_PATH)

    with open(JS_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    if OLD_AUTH_AND_FETCH in content and not os.path.exists(BAK_PATH):
        shutil.copyfile(JS_PATH, BAK_PATH)

    if OLD_AUTH_AND_FETCH not in content:
        print("ℹ️ Файл уже пропатчен или имеет другую структуру.")
        return

    content = content.replace(OLD_AUTH_AND_FETCH, NEW_AUTH_AND_FETCH)
    content = content.replace(OLD_NOTIF_POLL, NEW_NOTIF_POLL)

    with open(JS_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print("✅ Новый файл index-DfO6stMJ.js успешно адаптирован (авторизация + сброс ошибок по клику)!")


if __name__ == "__main__":
    main()

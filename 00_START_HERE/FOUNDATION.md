# ACP — Agent Commerce Protocol

> Верховный документ. Обязателен в любой сессии ACP.
> v0.3 — 2026-06-25 — финальный фрейминг: tool-not-product, L402 complement, zero-config

---

## §0. ПРИРОДА ПРОЕКТА

ACP — **НЕ** продукт, **НЕ** компания, **НЕ** токен.
ACP — **открытый протокол**: discovery + atomic delivery + receipt + reputation
для AI-агентов. Payment = pluggable (L402, Lightning, Cashu).

### Аналогия

| Слой | Интернет | Agent commerce |
|---|---|---|
| Discovery | DNS | **ACP (Nostr manifests)** |
| Payment | TCP | L402 / Lightning / Cashu |
| Atomic delivery | TLS | **ACP (hold invoice + preimage)** |
| Proof | Server logs | **ACP (Nostr receipts)** |
| Trust | CA system | **ACP (attestations)** |

L402 = payment transport. ACP = всё остальное. Не конкурент — дополнение.

---

## §1. ПОЧЕМУ ЭТО НУЖНО

### Проблема

Модели решают 90% задач сами. Но модель **физически не может КУПИТЬ**.
L402 решает payment. Но L402 не имеет: discovery, atomic delivery, receipt, reputation.

### Решение

ACP = **tool в toolbelt агента.** Плагин в любой фреймворк (Claude Code, Hermes,
Codex, LangChain). Даёт агенту способность: находить → платить → получать
гарантированно → доказывать покупку.

### Три роли

```
ЧЕЛОВЕК
  │ даёт wallet (одна строка) + подтверждение покупки
  ▼
АГЕНТ (любой фреймворк + ACP tool)
  │ discovery (Nostr) + payment (L402/LN/Cashu) + atomic delivery + receipt
  ▼
ПРОВАЙДЕР (native / bridge / adapter)
```

### Типы провайдеров

| Тип | Payment rail | Пример |
|---|---|---|
| Native | Lightning direct / L402 | VPN за саты |
| Bridge | Lightning ← → Stripe API | Notion через bridge-agent |
| Adapter | Существующий сервис | Bitrefill gift cards |

**Протокол нейтрален к payment rail и к тому, как провайдер исполняет.**

---

## §2. ПРИНЦИПЫ

### 2.1 Пользователь = видит результат, не механизм
ACP = под капотом. Пользователь даёт wallet → говорит «купи» → получает результат.

### 2.2 Zero-config
Единственное что даёт пользователь — **кошелёк** (NWC URI или API key).
Всё остальное (keypair, relays, discovery) — автоматически.

### 2.3 Агент = кассир
Агент показывает цену → ждёт подтверждения → исполняет. Не тратит самовольно.

### 2.4 Кошелёк = prepaid с лимитом
Человек грузит N сатов. Агент НЕ может потратить больше. Без fraud risk.

### 2.5 Протокол нейтрален к ЗНАЧЕНИЮ, строг к ФОРМАТУ
Формат pricing — в протоколе. Значения — нет. Формат events — в протоколе.
Алгоритм репутации — нет.

### 2.6 Payment = pluggable
ACP не привязан к Lightning. L402, Cashu, Solana Pay — любой рельс через
`pay_endpoint` format field.

### 2.7 Не конкурент L402 — дополнение
L402 = «как заплатить». ACP = «как найти, доверять, гарантировать, доказывать».

---

## §3. ЧТО В ПРОТОКОЛЕ, ЧТО НЕ В ПРОТОКОЛЕ

| В протоколе | НЕ в протоколе |
|---|---|
| Event format (tags, kinds) | Значения цен |
| Discovery (Nostr relay query) | Какие релеи |
| Payment endpoint format | Выбор payment rail |
| Atomic delivery (preimage = key) | Как провайдер исполняет |
| Receipt (preimage proof) | Алгоритм репутации |
| Confirmation flow (tool interface) | UI агента |
| Budget limits (wallet interface) | Конкретные лимиты |
| Provider types (native/bridge/adapter) | Конкретные bridge-провайдеры |

---

## §4. СТАДИИ

| Стадия | Критерий | Статус |
|---|---|---|
| v0 — Spec draft | Спека | ✅ |
| v1 — Spec interop-readable | ИИ реализует по спеке | ✅ |
| v2 — Reference impl | Python SDK + tests | ✅ |
| v3 — Cross-lang interop | Python ↔ TS via relay | ✅ |
| v4 — Published | GitHub + NIP + docs | ⬜ NEXT |
| v5 — First adoption | Незнакомец строит на ACP | ⬜ |
| v6 — Self-sustaining | Автора нет, агенты торгуют | ⬜ |

---

## §5. РАЗДЕЛ ТРУДА

| Кто | Что | Чего НЕ делает |
|---|---|---|
| Я (Hermes) | Спека, SDK, harness, тесты, код | Outreach, бинарные решения |
| Ты | Quality control, veto, решения, outreach | Код, архитектура |

WHY — твоё. HOW — моё. WHAT — совместно.
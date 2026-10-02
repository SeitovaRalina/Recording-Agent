# Internal Update Style Guide

How engineers on Recording Agent write **daily status updates** in the project's Mattermost
channel.

Updated 2026-09-30 after lead feedback: updates were too long to read. The reader is a busy
lead, product owner or colleague who must understand in a few seconds what was done, what was
not, and what is needed from them. Details — technical or not — are given only when someone
asks.

---

## The skeleton (fixed order)

```
UPD <DD.MM>

Сделано:
- ...

Не сделано:
- ...

Блокеры:
- ...

Следующие шаги:
- ...
```

`Не сделано` and `Блокеры` stay even when empty — write `— нет`. An absent section reads as
"forgot", an explicit `нет` reads as "checked".

---

## Rules

- **One short sentence per bullet.** What was done and, if needed, how it works now — in one
  sentence. No lists of fields, file names, counts, examples or explanations of why. If a task
  tracker is used, the task name is enough.
- **Impersonal, third person**: «настроено», «проверены доступы», «реализована», not «настроила»,
  «я проверила».
- **Address colleagues with «Вы».** A blocker tags the person and says exactly what is needed and
  for what: «@Имя, пришлите, пожалуйста, [доступ / данные] [к чему]».
- **No manual line breaks inside a bullet.** Mattermost keeps them. One bullet is one line.
- **`Не сделано`** says what did not get done and when it will be picked up.
- **`Следующие шаги`** — one to three items, each with a checkable outcome, as short as `Сделано`.
- Honest status: do not report as done what is not done, and correct an earlier wrong figure in
  the next update («уточнение: было X, стало Y»).

---

## Example

```
UPD 30.09

Сделано:
- Проведена проверка деплоя после слияния в main - всё работает на новом релизе.
- Проверены доступы Лили: Диск, Календарь, Notion, Synology и личка с ботом доступны.
- Разобраны базы Notion Лили - схема отличается от базы Антона, нужна своя схема полей на рекрутера.

Не сделано:
- Подключение Лили - после мультипользовательности, завтра.

Блокеры:
- @Lilia Akentyeva, подтвердите, пожалуйста, что записи кладём в /Recruiting-NE/2. Interviews.

Следующие шаги:
- Мультипользовательность: своя схема Notion и свои папки Synology для каждого рекрутера.
- Подключение Лили и её первый скан.
```

Too long — do not do this:

```
- Проведена полная проверка деплоя после слияния в main - бэкенд работает на новом релизе, навык Милы и диспетчер автомаршрутизации не откатились, флаги не изменились. Ежедневный скан и сводка в 18:00 отрабатывают каждый день, ошибок в логах бэкенда с момента деплоя нет.
```

---

## Hard NOs

- First-person forms, «ты» towards colleagues, hand-wrapped lines.
- Technical detail in the body: file paths, class names, commands, branches, commit counts,
  field lists. Give it when asked.
- «Тесты зелёные», «CI прошёл» — preconditions, not results.
- Secrets or anything that looks like one: tokens, passwords, OAuth codes.
- Real candidate names from production data.
- Process and methodology. The plan is `.memory-bank/current-work.md`, not a daily.
- Wellbeing, apologies, tool-limit complaints.

---

Last updated: 2026-09-30

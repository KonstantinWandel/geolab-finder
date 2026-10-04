# React + Vite

## GeoDB Index Date

The `inkar` app's filter note displays only the localized index date. The shared
`formatIndexDate` helper uses the Berlin calendar date, de-DE numeric formatting
and en-GB long-month formatting; unusable dates hide the note. SOEP/all-mode
summary content and every filter remain unchanged.

Run `node --test frontend/src/i18n.test.js` from the repository root. The existing
webshot environment checks a staged build or the live GeoDB without searches or
visitor telemetry:

```sh
/home/researcher/miniconda3/envs/webshot/bin/python tests/index_date_browser.py \
  --build frontend/dist-inkar --output /tmp/geodb-index-date/build-report.json
/home/researcher/miniconda3/envs/webshot/bin/python tests/index_date_browser.py \
  --url https://geodb.geolab.soz.uni-bielefeld.de/ \
  --output /tmp/geodb-index-date/live-report.json
```

Both languages are tested at 1440px and 390px; staged checks additionally cover
missing/invalid dates. Inspect every generated screenshot. Shared changes belong
in both finder repositories. Publish only GeoDB's build, retain old hashed assets
for open browser tabs, and leave SOEP and all other app roots unchanged.

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Babel](https://babeljs.io/) (or [oxc](https://oxc.rs) when used in [rolldown-vite](https://vite.dev/guide/rolldown)) for Fast Refresh
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/) for Fast Refresh

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend using TypeScript with type-aware lint rules enabled. Check out the [TS template](https://github.com/vitejs/vite/tree/main/packages/create-vite/template-react-ts) for information on how to integrate TypeScript and [`typescript-eslint`](https://typescript-eslint.io) in your project.

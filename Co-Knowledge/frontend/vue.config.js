const path = require('path');

const publicPath = process.env.BASE_URL

function resolve (dir) {
  return path.join(__dirname, dir)
}
// 打包时间戳
process.env.VUE_APP_TIME_STAMP = new Date().getTime()
const isDevelopment = process.env.VUE_APP_ENV === 'development'

// 浏览器标签标题：填产品名，保证独立部署时 document.title 不为空。
// 运行时的兜底与 `<html lang>` 见 src/app/main.js。
const title = 'Knowledge Studio'
const pages = {
  app: {
    entry: 'src/app/main.js',
    template: 'public/index.html',
    // 在 dist/index.html 的输出
    filename: 'index.html',
    // 当使用 title 选项时，
    // template 中的 title 标签需要是 <title><%= htmlWebpackPlugin.options.title %></title>
    title: title,
  }
}

const _legacyConfig_ = {
  publicPath,
  pages,
  configureWebpack: config => {
    if (isDevelopment) {
      config.devtool = 'eval-source-map'
    }
    return {
      output: {
        library: 'ai',
        // 将你的 library 暴露为所有的模块定义下都可运行的方式
        libraryTarget: 'umd',
        // 按需加载相关，设置为 webpackJsonp_saasApp 即可
        // jsonpFunction: 'webpackJsonp_saas' // webpack 4
        chunkLoadingGlobal: 'webpackJsonp_ai'
      },
      plugins: [
        // new CopyWebpackPlugin()
      ],
      // optimization:{
      //   minimize: false
      // },
      resolve: {
        alias: {
          '@': resolve('./src')
        }
      },
    }
  },
  // transpileDependencies: [/node_modules\/json[^/]+/, /node_modules\/vanilla-jsoneditor/],
  transpileDependencies: [/node_modules/],
  chainWebpack: config => {
    config
      // .plugin('html')
      .plugin('html-app')
      .tap(args => args)
  },
  lintOnSave: 'warning',
  productionSourceMap: process.env.NODE_ENV !== 'production',
  devServer: {
    host: 'localhost',
    port: 8808,
    server: 'http',
    allowedHosts: "all",
    client: {
      overlay: false
    },
    proxy: devProxy()
  }
}

/**
 * `devServer.proxy`：把 /api 前缀转发到 `VUE_APP_API`。
 *
 * ⚠️ **必须过滤掉 key 或 target 为 undefined 的条目**，否则 `npm run serve` 直接起不来：
 * webpack-dev-server 4.15 在 `initialize()` 里会遍历 proxy 中间件并读 `proxyConfig.ws`，
 * 遇到 `target: undefined` 的条目时抛
 *   `TypeError: Cannot read properties of undefined (reading 'upgrade')`
 * —— 报错点在 node_modules 里，完全指不到配置上，很容易被误判成「仓库坏了」。
 *
 * `VUE_APP_API` 只在 `.env.local` 里（见 `.env.example`），默认没有；`VUE_APP_*_BASE`
 * 那几个则来自 `.env`。缺哪个就跳过哪条，开发态照常启动，只是那个前缀不代理。
 */
function devProxy () {
  const target = process.env.VUE_APP_API
  // 后端所有路由共用一个前缀，开发态只需要代理这一条。
  const entries = [
    [process.env.VUE_APP_KBASE_BASE]
  ]
  const proxy = {}
  for (const [context] of entries) {
    if (context && target) {
      proxy[context] = { target, changeOrigin: true }
    }
  }
  return proxy
}

module.exports = (function (config) {

  function filter(config) {
    config.lintOnSave = false
    let webpackConfig = config.chainWebpack
    config.chainWebpack = (config) => {
      config.module
        .rule('vue')
        .use('vue-loader')
        .tap((options) => {
          return {
            ...options,
            // compilerOptions: {
            //   compatConfig: {
            //     MODE: 2
            //   }
            // }
          }
        })
      if (typeof webpackConfig === 'function') {
        webpackConfig(config)
      }

      // vue3 全家桶别名

    }
    return config
  }

  return function (...args) {
    let _config
    if (typeof config === 'function') {
      _config = config(...args)
    } else {
      _config = config
    }
    return (_config instanceof Promise) ? _config.then(config => filter(config)) : filter(_config)
  }
}(_legacyConfig_))

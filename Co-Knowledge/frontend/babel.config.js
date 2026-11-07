const plugins = ["@babel/plugin-transform-optional-chaining", "@babel/plugin-transform-nullish-coalescing-operator"]
if (process.env.NODE_ENV !== 'development') {
  plugins.push(["transform-remove-console", { "exclude": ["error", "warn"] }])
}
module.exports = {
  // presets: [
  //   '@vue/cli-plugin-babel/preset'
  // ]
  "presets": [
    [
      "@vue/app",
      {
        "useBuiltIns": "entry"
      }
    ],
    [
      "@babel/preset-env", 
      {
        "targets": {
          "browsers": [
            "Firefox >= 60",
            "Chrome >= 75",
            "Firefox >= 60",
            "not dead",
            "not ie <= 11"
          ]
        },
        "useBuiltIns": "entry",  // 按需自动引入 polyfill
        "corejs": 3             // 指定 core-js 版本（需提前安装）
      }
    ]
  ],
  plugins,
}
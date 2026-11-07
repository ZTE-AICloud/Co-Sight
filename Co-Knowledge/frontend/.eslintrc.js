module.exports = {
  "env": {
    browser: true,
    es6: true,
    node: true,
    'vue/setup-compiler-macros': true,
  },

  "plugins": [
    "vue",
    "import",
  ],

  "extends": [
    // "plugin:vue/recommended",
    "plugin:vue/vue3-recommended"
  ],

  "globals": {
    "ClipboardItem": "readonly",
    "Atomics": "readonly",
    "SharedArrayBuffer": "readonly",
    "$": "readonly",
    "document": "readonly",
    "jquery": "readonly",
    "module": "readonly",
    "navigator": "readonly",
    "process": "readonly",
    "require": "readonly",
    "UE": "readonly",
    "window": "writable",
  },

  "parserOptions": {
    "parser": "babel-eslint",
    "ecmaVersion": 2020,
    "sourceType": "module",
  },

  "rules": {
    /**
     * ---- 项目组可自己配置的规则，但不能覆盖下面DT统一的规则 ----
     */

    "vue/no-mutating-props": "off",
    // vue
    // 组件的props是否必须设置类型和required属性
    "vue/require-prop-types": 0,
    "vue/require-default-prop": 0,
    // 除非使用富文本变量，否则不要关闭
    // "vue/no-v-html": 0,
    // 组件名称必须是 串式命名法（kebab-case）。关闭，不做强制要求
    "vue/multi-word-component-names": 0,
    // 一行/多行的标签，一行内允许的属性数量。设置为5个
    "vue/max-attributes-per-line": ["warn", {
      "singleline": { "max": 5  },
      "multiline": { "max": 5 }
    }],

    // JS
    // 检查魔鬼数字，-1 0 1 除外
    "no-magic-numbers": ["warn", { "ignore": [-1, 0, 1, 2] }],
    // 禁止出现多个空格
    "no-multi-spaces": "warn",
    // 禁止使用 空格 和 tab 混合缩进
    "no-mixed-spaces-and-tabs": "warn",
    // 禁用 debugger
    "no-debugger": "error",

    /**
     * ---- 下面是DT统一的编码规范，不允许修改 -----
     */

    /**
     * es6规范：禁止规则，团队必须修复
     */
    // 6.1【禁止】永远不要在字符串中使用 eval()
    "no-eval": "error",
    // 7.1【禁止】永远不要使用函数构造方法创建一个新的函数
    "no-new-func": "error",
    // 7.2【禁止】不要将参数命名为arguments
    // "prefer-rest-params": "error",
    // 10.1【禁止】[ES6]在import语句里不允许Webpack loader语法
    "import/no-webpack-loader-syntax": "error",
    // 13.1【禁止】禁止存在未使用的变量
    "no-unused-vars": "error",
    // 13.2【禁止】不要链式声明变量
    "no-multi-assign": "error",
    // 15.1【禁止】不要使用with语句
    "no-with": "error",

    /**
     * es6规范：强制规则，团队必须修复
     */
    // 2.1【强制】声明变量必须加上var/let
    // 13.3【强制】[ES6]使用 const 或者 let 声明变量
    "no-undef": "error",
    // 2.2【强制】[ES6]如果一个变量不会被重新赋值，最好使用const进行声明
    // "prefer-const": "error", // 降为参考
    "no-const-assign": "error",
    // 2.3【强制】[ES6]如果你需要对变量进行重新赋值，那就使用let，而不是var
    "no-var": "error",
    // 3.1【强制】使用字面值创建对象
    "no-new-object": "error",
    // 3.2【强制】不要直接调用Object.prototype上的方法
    "no-prototype-builtins": "error",
    // 3.3【强制】当创建一个带有动态属性名的对象时，使用属性名表达式定义对象属性
    "no-useless-computed-key": "error",
    // 4.1【强制】使用字面量创建数组
    "no-array-constructor": "error",
    // 7.4【强制】把立即执行函数包裹在圆括号里
    "wrap-iife": "error",
    // 8.1【强制】[ES6]当你必须使用匿名函数（例如回调函数）时，请使用箭头函数。
    "prefer-arrow-callback": "error",
    "arrow-spacing": "error",
    // 8.2【推荐】[ES6]如果函数体由一个没有副作用的expression语句组成，删除大括号和return。否则，继续用大括号和 return 语句。
    // 8.4【推荐】[ES6]如果函数只有一个参数，就删除其括号
    "arrow-parens": ["warn", "as-needed"],
    // "arrow-body-style": ["warn", "as-needed"],
    // 10.2【强制】[ES6]所有的import语句放到非import语句之前
    "import/first": "error",
    // 14.1【强制】使用 === and !== 不要使用 == and !=
    "eqeqeq": "error",
    // 15.2【强制】区块起首的大括号跟在关键字的后面，不要另起一行
    "no-unreachable": "error",
    "no-lone-blocks": "error",
    // 15.3【强制】总是使用大括号包裹代码块
    // 15.4【强制】else和if的关闭大括号在同一行
    "brace-style": "error",
    // 16.1【强制】switch语句，每个case分支必须使用break结尾，最后必须以default分支结束。禁止出现重复的case。
    "no-fallthrough": "error",
    "default-case": "error",
    "no-duplicate-case": "error",

    /**
     * es6规范：推荐规则，作为团队参考，不做强制要求，建议团队遵守
     */
    // 3.4【推荐】[ES6]使用方法简写
    // 3.5【推荐】[ES6]使用属性简写
    "object-shorthand": "warn",
    // 3.7【推荐】仅在无效的标识符的属性上使用单引号
    "quote-props": ["warn", "as-needed"],
    // 3.8【推荐】[ES6]对象浅拷贝，使用扩展运算符（...运算符）优先于使用Object.assign 方法
    "prefer-object-spread": "warn",
    // 5.1【推荐】[ES6]使用解构赋值来获取和使用对象的一个或多个属性
    // 5.2【推荐】[ES6]使用数组解构
    // "prefer-destructuring": "warn",
    // 6.5【推荐】[ES6]以表达式构建字符串时，使用模板字符串而不是串联.
    "prefer-template": "warn",
    "template-curly-spacing": ["warn", "never"],
    // 7.3【推荐】不要对参数重新赋值
    // "no-param-reassign": "error",
    // 7.5【推荐】用函数表达式而不是函数声明
    // "func-style": "warn",
    // 7.6【推荐】不要在非函数块中声明函数 (例如if, while, 等等)
    "no-loop-func": "warn",
    // 7.7【推荐】不要使用 arguments, 用rest参数 ... 替代
    "prefer-rest-params": "warn",
    // 7.11【推荐】在函数定义的时候插入合适的空格
    "space-before-function-paren": ["warn", "always"],
    // "space-before-blocks": "warn",
    // 7.13【推荐】[ES6]优先使用扩展运算符...调用可变函数
    "prefer-spread": "warn",
    // 8.5【推荐】[ES6]避免箭头函数 (=>) 和比较操作符 (<=, >=)混淆
    "no-confusing-arrow": "warn",
    // 10.3【推荐】[ES6]使用 (import/export) 模块
    "import/no-commonjs": "warn",
    // 10.4【推荐】[ES6]不要使用通配符导入
    "import/no-namespace": "warn",
    // 10.5【推荐】[ES6]一个路径只 import 一次
    "no-duplicate-imports": "warn",
    // 10.7【推荐】[ES6]不要导出可变的东西
    "import/no-mutable-exports": "warn",
    // 10.8【推荐】[ES6]在一个单一导出模块里，用 export default 更好
    // "import/prefer-default-export": "warn",
    // 11.1【推荐】[ES6]不要使用迭代器. 使用Javascript的高级函数替代for-in or for-of
    "no-iterator": "warn",
    "no-restricted-syntax": ["warn", "WithStatement", "BinaryExpression[operator='in']", "BinaryExpression[operator='of']"],
    // 14.4【推荐】三元表达式不应该嵌套，通常是单行表达式
    "no-nested-ternary": "warn",
    // 14.5【推荐】避免不需要的三元表达式
    "no-unneeded-ternary": "warn",
    // 15.5【推荐】减少不必要的else和else if语句块
    "no-else-return": "warn",
    // 17.1【推荐】多行注释用 /** ... */
    // "multiline-comment-style": "warn",
    // 18.3【推荐】使用2个空格做缩进
    "indent": ["warn", 2],
    // 18.4【推荐】在大括号前空一格
    "space-before-blocks": "warn",
    // 18.5【推荐】在控制语句 (if, while)的圆括号前空一格。 在函数调用和定义时，参数列表和函数名之间不空格
    "keyword-spacing": "warn",
    // 18.6【推荐】用空格来隔开运算符
    "space-infix-ops": "warn",
    // 18.7【推荐】文件结尾空一行
    "eol-last": "warn",
    // 18.8【推荐】当出现长的调用链（>2个）时用缩进。用点开头强调该行是一个方法调用，而不是一个新的语句
    "newline-per-chained-call": "warn",
    "no-whitespace-before-property": "warn",
    // 18.10 【推荐】圆括号里不要加空格
    "space-in-parens": "warn",
    // 18.11【推荐】方括号里不要加空格
    "array-bracket-spacing": "warn",
    // 18.12【推荐】大括号里加空格
    "object-curly-spacing": ["warn", "always"],
    // 18.13【推荐】作为语句的花括号内也要加空格 —— { 后和 } 前都需要空格
    "block-spacing": "warn",
    // 18.14【推荐】,前不要空格，,后需要空格
    "comma-spacing": "warn",
    // 18.15【推荐】计算属性的大括号内添加空格
    "computed-property-spacing": "warn",
    // 18.16【推荐】调用函数时，函数名和小括号之间不要空格
    "func-call-spacing": "warn",
    // 18.17【推荐】在对象的字面量属性中， key value 之间要有空格
    "key-spacing": "warn",
    // 18.18【推荐】行末不要出现空格
    "no-trailing-spaces": "warn",
    // 19.1【推荐】不要前置逗号
    "comma-style": "warn",
    // 20.1【推荐】禁止对 String，Number 和 Boolean 使用 new 操作符
    "no-new-wrappers": "warn",
    // 20.2【推荐】对数字字符串使用函数进行转换
    "radix": "warn",
    // 21.1【推荐】避免使用一个字母命名，让你的命名可表达正确的意图
    // "id-length": "warn",
    // 21.2【推荐】使用小驼峰命名变量、对象、属性、函数和实例
    "camelcase": ["warn", { allow: ["[_A-Z]+"] }],
    // 21.3【推荐】构造函数/类/模块对象定义，采用首字母大写的PascalCase命名法
    "new-cap": "warn",
    // 23.1【推荐】使用 Number.isNaN 替换全局函数 isNaN
    // 23.2【推荐】使用 Number.isFinite 替换全局方法 isFinite
    "no-restricted-globals": ["warn", "isNaN", "isFinite"],
    "space-unary-ops": "warn",
    /**
     * es6规范：参考, 默认不检查，团队可以自己打开检查项
     */
    // 2.2【强制】[ES6]如果一个变量不会被重新赋值，最好使用const进行声明
    // "prefer-const": "error", // 降为参考
    // 3.9【参考】禁止修改内置对象原型
    "no-extend-native": "warn",
    // 6.2【参考】字符串使用单引号
    "quotes": ["warn", "single"],
    // 6.3【参考】不要使用不必要的转义字符
    "no-useless-escape": "warn",
    // 7.12【参考】不要改变参数
    // "no-param-reassign": ["warn", { "props": true }],
    // changed eslint rule
    "no-param-reassign": ["off", { "props": false }],
    // 7.15【参考】函数定义或者调用时有多个参数，如不能一行显示，则采用一个参数一行，每个参数后带有逗号
    // "function-paren-newline": "warn",
    // 8.6【参考】[ES6]箭头函数使用隐式return时，函数体就放在箭头后面
    "implicit-arrow-linebreak": "warn",
    // 9.5【参考】如果未指定，则类具有一个默认的构造函数。 空的构造函数或者仅委托给父类的构造函数是不需要的
    "no-useless-constructor": "warn",
    // 9.6【参考】避免重复的类成员
    "no-dupe-class-members": "warn",
    // 12.2【参考】访问一般属性时使用点符号
    "dot-notation": "warn",
    // 13.4【参考】每个变量声明或者赋值都要使用一个const, let 或 var
    "one-var": ["warn", "never"],
    // 13.7【参考】禁止使用运算符 (++, --)，推荐使用(+=,-=)代替
    // "no-plusplus": "warn",
    // 13.8【参考】在赋值的时候避免在 = 前后换行
    "operator-linebreak": "warn",
    // 13.9【参考】避免使用全局变量
    "no-implicit-globals": "warn",
    // 17.2【参考】单行注释使用//，并将单行注释放到被注释代码前一行
    // "line-comment-position": "warn",
    // 17.3【参考】所有注释开头都加一个空格
    "spaced-comment": "warn",
    // 18.1【参考】代码块中不要包含无用空行
    "padded-blocks": ["warn", "never"],
    // 18.2【参考】不要在代码之间包含多个空行
    "no-multiple-empty-lines": "warn",
    // 18.19【参考】一行代码不应超过100个字符(包括空格). 注意: 长字符串除外above
    // "max-len": ["warn", { "code": 100 }],
    // 19.2【参考】在尾部添加逗号: Yup
    "comma-dangle": ["warn", "never"],

    // extends
    "curly": "error",

    /**
     * Vue规范：强制规则，必须遵守
     */
    // 1.3 计算型属性应该是同步的，而不是异步的
    "vue/no-async-in-computed-properties": "error",
    // 1.4 禁止重复命名
    "vue/no-dupe-keys": "error",
    // 1.5 禁止给同一个属性重复赋值
    "vue/no-duplicate-attributes": "error",
    // 1.6 报告template中的语法错误
    "vue/no-parsing-error": "error",
    // 1.7 禁止使用保留名
    "vue/no-reserved-keys": "error",
    // 1.8 组件的data属性必须是一个函数
    "vue/no-shared-component-data": "error",
    // 1.9 禁止在计算属性中出现副作用（修改原有数据）
    "vue/no-side-effects-in-computed-properties": "error",
    // 1.10 禁止将key用在template上
    "vue/no-template-key": "error",
    // 1.11 禁止在textarea中使用Mustache语法
    "vue/no-textarea-mustache": "error",
    // 1.12 禁止存在引入未使用的组件
    "vue/no-unused-components": "error",
    // 1.13 在v-for 或者 scope 中定义的变量必须被实际使用
    "vue/no-unused-vars": "error",
    // 1.14 禁止v-if 和 v-for作用在同一个元素上
    "vue/no-use-v-if-with-v-for": "error",
    // 1.16 prop type 必须是数据类型的构造函数
    "vue/require-prop-type-constructor": "error",
    // 1.17 渲染函数必须始终有返回值
    "vue/require-render-return": "error",
    // 1.18 v-for必须有v-bind:key
    "vue/require-v-for-key": "error",
    // 1.19 props 的默认值必须与其类型一致且有效
    "vue/require-valid-default-prop": "error",
    // 1.20 计算型属性最终要有return语句
    "vue/return-in-computed-property": "error",
    // 1.21 当 v-on 修饰的事件出现重复时，强制使用 exact进行区分
    "vue/use-v-on-exact": "error",
    // 1.22 template内容不能为空，必须包含根节点
    "vue/valid-template-root": "error",
    // 1.23 v-bind必须有效
    "vue/valid-v-bind": "error",
    // 1.24 有效的 v-cloak 指令
    "vue/valid-v-cloak": "error",
    // 1.25 有效的 v-else-if 指令
    "vue/valid-v-else-if": "error",
    // 1.26 有效的 v-else 指令
    "vue/valid-v-else": "error",
    // 1.27 有效的 v-for 指令
    "vue/valid-v-for": "error",
    // 1.28 有效的 v-html 指令
    "vue/valid-v-html": "error",
    // 1.29 有效的 v-if 指令
    "vue/valid-v-if": "error",
    // 1.30 有效的 v-model 指令
    "vue/valid-v-model": "error",
    // 1.31 有效的 v-on 指令
    "vue/valid-v-on": "error",
    // 1.32 有效的 v-once 指令
    "vue/valid-v-once": "error",
    // 1.33 有效的 v-pre 指令
    "vue/valid-v-pre": "error",
    // 1.34 有效的 v-show 指令
    "vue/valid-v-show": "error",
    // 1.35 有效的 v-text 指令
    "vue/valid-v-text": "error",
  },

  parserOptions: {
    parser: '@typescript-eslint/parser',
    ecmaVersion: 2020,
    sourceType: 'module'
  }
};

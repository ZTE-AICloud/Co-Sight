import {JigsawToast} from "@rdkmaster/jigsaw";
import {Message, MessageSource, Utils} from "@rdkmaster/lui-sdk";

export function addCopyIcon(message: Message): void {
    if (message.from != MessageSource.HUMAN) {
        return;
    }
    // 获取消息容器元素
    const messageContainer = document.querySelector(`[uuid="${message.uuid}"]`);
    if (!messageContainer) return;

    // 获取message-content-human元素
    const messageContent = messageContainer.querySelector('.message-content-human');
    if (!messageContent) return;

    // 检查是否已经存在复制图标
    if (messageContent.querySelector('.iconfont-e9c1')) return;

    // 创建复制图标元素
    const copyIcon = document.createElement('i');
    // 添加 human-copy-icon 类用于控制显示/隐藏
    copyIcon.className = 'human-copy-icon iconfont iconfont-e9c1';
    copyIcon.title = '复制';
    // 默认隐藏
    copyIcon.style.visibility = 'hidden';

    // 添加鼠标进入事件
    messageContent.addEventListener('mouseenter', () => {
        copyIcon.style.visibility = 'visible';
    });

    // 添加鼠标离开事件
    messageContent.addEventListener('mouseleave', () => {
        // 检查鼠标是否在复制图标上
        if (!copyIcon.matches(':hover')) {
            copyIcon.style.visibility = 'hidden';
        }
    });

    // 为复制图标添加鼠标事件
    copyIcon.addEventListener('mouseenter', () => {
        copyIcon.style.visibility = 'visible';
    });

    copyIcon.addEventListener('mouseleave', () => {
        copyIcon.style.visibility = 'hidden';
    });

    copyIcon.addEventListener('click', (event) => {
        let content = "";
        if (typeof message.initData == 'string') {
            content = message.initData;
        } else if (message.initData[0]) {
            content = message.initData[0].value;
        }
        Utils.execCopy(content).then(() => {
            JigsawToast.show('复制成功', {timeout: 5000});
        }).catch(() => {
            JigsawToast.show('复制失败', {timeout: 5000});
        })
    });

    messageContent.insertBefore(copyIcon, messageContainer.querySelector('.message-human'));
}

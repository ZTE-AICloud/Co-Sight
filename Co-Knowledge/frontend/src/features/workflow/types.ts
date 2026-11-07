/* eslint-disable no-unused-vars */
export enum ComponentEnum {
  PRE_RETRIEVER = 'PRE_RETRIEVER',
  RETRIEVER = 'RETRIEVER',
  POST_RETRIEVER = 'POST_RETRIEVER',
  RESPONSE_SYNTHESIZER = 'RESPONSE_SYNTHESIZER'
}

export type ComponentType =
  ComponentEnum.PRE_RETRIEVER | ComponentEnum.RETRIEVER | ComponentEnum.POST_RETRIEVER |
  ComponentEnum.RESPONSE_SYNTHESIZER;

export interface ComponentTheme {
    theme: 'purple' | 'orange' | 'primary' | 'green';
    icon: any;
    iconGray?: any;
  }

export interface InputVariable {
    'key': string;
    'label': string;
    'sourceNode': string;
  };

export const ComponentThemes: Record<string, ComponentTheme> = {
  PRE_RETRIEVER: {
    theme: 'purple',
    icon: require('@/assets/LLMs1.svg'),
    iconGray: require('@/assets/LLMs1copy.svg')
  },
  RETRIEVER: {
    theme: 'orange',
    icon: require('@/assets/branch1.svg'),
    iconGray: require('@/assets/branch1copy.svg')
  },
  POST_RETRIEVER: {
    theme: 'primary',
    icon: require('@/assets/knowledge1.svg'),
    iconGray: require('@/assets/knowledge1copy.svg')
  },
  RESPONSE_SYNTHESIZER: {
    theme: 'green',
    icon: require('@/assets/response1.svg'),
    iconGray: require('@/assets/response1copy.svg')
  },
};

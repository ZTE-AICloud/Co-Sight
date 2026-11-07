import {
  Preretriever, Retriever, Postretriever, ResponseSynthesizer,
  OUTPUT_INTERVAL
} from '@/features/workflow/lib/workflow';

export default {
  data () {
    return {
      shapeAndConstMap: {
        PRE_RETRIEVER: Preretriever,
        RETRIEVER: Retriever,
        POST_RETRIEVER: Postretriever,
        RESPONSE_SYNTHESIZER: ResponseSynthesizer
      },
      shapeAndPortIdMap: {
        PRE_RETRIEVER: 'preretriever',
        RETRIEVER: 'retriever',
        POST_RETRIEVER: 'postretriever',
        RESPONSE_SYNTHESIZER: 'responsesynthesizer'
      }
    }
  },
  methods: {
    updateOuputPortForSingleOutput (target) {
      if (!target) {
        return
      }
      const shapeList = Object.keys(this.shapeAndConstMap);
      if (shapeList.indexOf(target.store.data.shape) === -1) {
        return
      }
      const incomingE = this.graph.getIncomingEdges(target.id)
      const numOfIncomingEdges = incomingE?.length
      let yIndex = 0;
      if (numOfIncomingEdges === 0 || !numOfIncomingEdges) {
        yIndex = this.shapeAndConstMap[target.store.data.shape].output.y
      } else if (numOfIncomingEdges === 1) {
        yIndex = this.shapeAndConstMap[target.store.data.shape].output_with_1_incoming_edge.y
      } else {
        yIndex = this.shapeAndConstMap[target.store.data.shape].output_with_1_incoming_edge.y + OUTPUT_INTERVAL * (numOfIncomingEdges - 1)
      }
      target.portProp(`${this.shapeAndPortIdMap[target.store.data.shape]}_output`, {
        group: 'out',
        args: {
          x: this.shapeAndConstMap[target.store.data.shape].output.x,
          y: yIndex
        }
      })
    },

    updatePortAfterChangingOperators (target, variables) {
      if (!target) {
        return
      }
      const operators = variables[this.shapeAndPortIdMap[target.store.data.shape]];
      const numOfOperators = operators.length
      let outputYIndex = 0;
      let inputYIndex = 0;
      if (numOfOperators === 0 || !numOfOperators) {
        outputYIndex = this.shapeAndConstMap[target.store.data.shape].output.y
        inputYIndex = this.shapeAndConstMap[target.store.data.shape].input.y
      } else {
        outputYIndex = this.shapeAndConstMap[target.store.data.shape].output.y + 24 * (numOfOperators - 1)
        inputYIndex = this.shapeAndConstMap[target.store.data.shape].input.y + 24 * (numOfOperators - 1)
      }
      target.portProp(`${this.shapeAndPortIdMap[target.store.data.shape]}_output`, {
        group: 'out',
        args: {
          x: this.shapeAndConstMap[target.store.data.shape].output.x,
          y: outputYIndex
        }
      })
      target.portProp(`${this.shapeAndPortIdMap[target.store.data.shape]}_input`, {
        group: 'in',
        args: {
          x: this.shapeAndConstMap[target.store.data.shape].input.x,
          y: inputYIndex
        }
      })
    }
  }
}

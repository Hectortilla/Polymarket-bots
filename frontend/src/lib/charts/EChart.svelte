<script lang="ts">
  import { onMount } from 'svelte';

  import { init, type EChartsCoreOption } from './echarts';

  let {
    option,
    label,
    class: className = ''
  }: { option: EChartsCoreOption; label: string; class?: string } = $props();
  let container: HTMLDivElement;
  let chart: ReturnType<typeof init> | undefined;
  let resizeFrame: number | null = null;

  const updateOptions = {
    notMerge: false,
    lazyUpdate: true,
    replaceMerge: ['series'],
    silent: true
  };

  onMount(() => {
    chart = init(container, undefined, {
      renderer: 'canvas',
      useDirtyRect: true
    });
    chart.setOption(option, updateOptions);
    let width = -1;
    let height = -1;
    const resize = new ResizeObserver(([entry]) => {
      if (!entry) return;
      const nextWidth = entry.contentRect.width;
      const nextHeight = entry.contentRect.height;
      if (nextWidth === width && nextHeight === height) return;
      width = nextWidth;
      height = nextHeight;
      resizeFrame ??= requestAnimationFrame(() => {
        resizeFrame = null;
        chart?.resize();
      });
    });
    resize.observe(container);
    return () => {
      resize.disconnect();
      if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
      chart?.dispose();
      chart = undefined;
    };
  });

  $effect(() => {
    chart?.setOption(option, updateOptions);
  });
</script>

<div bind:this={container} class={`echart ${className}`} role="img" aria-label={label}></div>

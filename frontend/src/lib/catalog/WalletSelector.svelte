<script lang="ts">
  import SelectionSearch from "./SelectionSearch.svelte";
  import { walletSelection } from "./walletSelection";
  let props: {
    value: string[];
    onchange: (values: string[]) => void;
    labelId: string;
    descriptionId?: string;
    invalid?: boolean;
    disabled?: boolean;
  } = $props();
</script>

<SelectionSearch source={walletSelection} {...props} />

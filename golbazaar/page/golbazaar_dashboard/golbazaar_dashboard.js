frappe.provide("golbazaar.pages");

frappe.pages["golbazaar_dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Golbazaar Dashboard",
		single_column: true,
	});

	const $container = $(
		'<div class="golbazaar-dashboard-container" style="padding: 1rem 0;"><div id="golbazaar-vue-root"></div></div>'
	).appendTo(page.body);

	const { createApp, ref, onMounted } = Vue;

	const App = {
		setup() {
			const loading = ref(true);
			const items = ref([]);
			const error = ref("");

			const loadItems = () => {
				loading.value = true;
				frappe.call({
					method: "golbazaar.api.items.get_latest_items",
					args: { limit: 10 },
				}).then(r => {
					items.value = r.message || [];
				}).catch(e => {
					error.value = (e && e.message) || "Failed to load items";
				}).finally(() => {
					loading.value = false;
				});
			};

			onMounted(loadItems);
			return { loading, items, error, loadItems };
		},
		template: `
			<div>
				<div class="d-flex justify-content-between align-items-center mb-3">
					<h4 class="mb-0">Latest Items</h4>
					<button class="btn btn-sm btn-outline-secondary" @click="loadItems">Refresh</button>
				</div>
				<div v-if="loading" class="text-muted">Loading...</div>
				<div v-else>
					<div v-if="error" class="alert alert-danger">{{ error }}</div>
					<div v-if="!items.length" class="text-muted">No Items found.</div>
					<div v-else class="table-responsive">
						<table class="table table-hover">
							<thead>
								<tr>
									<th>Name</th>
									<th>Item Name</th>
									<th>Group</th>
									<th>UOM</th>
									<th>Status</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="it in items" :key="it.name">
									<td><a :href="'/app/item/' + it.name">{{ it.name }}</a></td>
									<td>{{ it.item_name || it.name }}</td>
									<td>{{ it.item_group || '-' }}</td>
									<td>{{ it.stock_uom || '-' }}</td>
									<td>
										<span v-if="it.disabled" class="badge bg-danger">Disabled</span>
										<span v-else class="badge bg-success">Active</span>
									</td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>
			</div>
		`,
	};

	createApp(App).mount($container.find('#golbazaar-vue-root')[0]);
};


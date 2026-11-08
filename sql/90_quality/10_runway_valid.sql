-- Every judge runway is NULL (no shortfall) or between 0 and 120.
select account_id from marts.mart_shock_runways
where not (coalesce(runway_no_shock, 0) between 0 and 120
       and coalesce(runway_job_loss_ei55, 0) between 0 and 120
       and coalesce(runway_bills_up_15, 0) between 0 and 120
       and coalesce(runway_furnace_1_month, 0) between 0 and 120
       and coalesce(runway_job_loss_plus_bills, 0) between 0 and 120)
   or (select count(*) from marts.mart_shock_runways) <> 4500;

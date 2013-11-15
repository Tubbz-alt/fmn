<%inherit file="master.mak"/>
<div class="jumbotron">
  <h1>${current.name} preferences</h1>
  <p>${current.description}</p>
</div>
<div class="row">
  <div class="md-col-6">
    <p>You have ${len(preference.chains)} filter chains
    defined for this messaging context.</p>
  </div>
</div>
<div class="row">
  <form class="form-inline" role="form" action="/api/chain/new" method="post">
    <div class="form-group">
      <label class="sr-only" for="chain_name">Email address</label>
      <input type="text" class="form-control" name="chain_name" id="chain_name" placeholder="New Chain Name">
    </div>
    <input name="username" id="username" value="${username}" type="hidden">
    <input name="context" id="context" value="${current.name}" type="hidden">
    <button type="submit" class="btn btn-success">&#43; Create New Chain</button>
  </form>
</div>
<div class="row">
  <div class="md-col-6">
    <ul>
      % for chn in preference.chains:
      <li><a href="${chn.name}">${chn.name}</a></li>
      %endfor
    </ul>
  </div>
</div>